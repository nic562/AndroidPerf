import os
import abc
import time
import datetime
from decimal import Decimal
from threadpool import ThreadPool, WorkRequest

from .cpu import SysCPU, AppCPU
from .data_unit import DataUnit, MB
from .adb_with_tools import AdbProxyWithToolsAll, AppInfo
from .log import default as logging


class AppPerfBaseHelper(metaclass=abc.ABCMeta):
    app: AppInfo

    def __init__(self, adb: AdbProxyWithToolsAll, main_process_only=False):
        self.adb = adb
        self.main_process_only = main_process_only
        self._th_pool = ThreadPool(21)
        self.app = None

    @staticmethod
    def second2str(seconds: float) -> str:
        if seconds > 3600:
            return '%d时%d分%d秒' % (seconds // 3600.0, seconds % 3600 // 60.0, seconds % 60)
        return '%d分%d秒' % (seconds // 60.0, seconds % 60)

    @staticmethod
    def decimal_format(d, fm=Decimal('0.00')):
        return Decimal(str(d)).quantize(fm)

    def set_app(self, app: AppInfo):
        self.app = app

    def get_cpu_usage(self, pid=None, pid_list=None) -> (SysCPU, AppCPU):
        sys_cpu = self.adb.get_cpu_global()
        if pid:
            return sys_cpu, self.adb.get_process_cpu_usage(pid)
        return sys_cpu, self.adb.get_processes_cpu_usage(pid_list or self.adb.find_process_ids(self.app.pkg))

    def get_memory_usage(self, pid=None, pid_list=None, unit: DataUnit = None):
        if pid:
            return self.adb.get_process_memory(pid, unit=unit)
        return self.adb.get_processes_memory(pid_list or self.adb.find_process_ids(self.app.pkg), unit=unit)

    def exit(self, kill_tools=True, kill_process=True):
        try:
            self.adb.close(kill_tools=kill_tools)
        except Exception as e:
            logging.error("Close Adb error:\n\n%s", e)
        finally:
            if kill_process:
                os._exit(0)

    @abc.abstractmethod
    def on_test_cpu_memory(self, current_second: int, max_listen_seconds: int, data: dict):
        # 调用 start_test_cpu_memory后，在min_wait_seconds之后，每秒读取CPU、内存数据后要执行的操作。
        # 注意这里可能会在多个线程中执行(请做好状态同步)，执行耗时太长的操作会一直占用线程池资源。
        raise NotImplementedError

    def _async_on_test_cpu_memory(self, current_second: int, max_listen_seconds: int, min_wait_seconds: int,
                                  raw_data: dict, data: dict):
        logging.debug(f'{datetime.datetime.now()} On Test {current_second}th second!')
        if len(raw_data) < min_wait_seconds:
            # 取数少于n秒的不进行后续操作
            return
        self.on_test_cpu_memory(current_second, max_listen_seconds, self._compute_cpu_memory(raw_data, data))

    def _compute_cpu_memory(self, raw_data: dict, data: dict):
        # 多个线程读取性能数据，计算时需重新按时序排列
        sort_data = sorted(raw_data.items(), key=lambda x: x[0])
        cpu_list = []
        memory_list = []
        for idx, d in enumerate(sort_data):
            if idx == 0:
                continue
            f_d = sort_data[idx - 1][1]
            _d = d[1]
            cpu, _ = self.adb.compute_cpu_rate(f_d['cpu_g'], _d['cpu_g'], f_d['cpu_a'], _d['cpu_a'])
            memory = _d['memory']
            logging.debug('current CPU:[%.2f], MEM:[%.2f]', cpu * 100, memory)
            cpu_list.append(cpu)
            memory_list.append(memory)
        data['cpu'] = cpu_list
        data['memory'] = memory_list
        return data

    def _async_run_get_cpu_memory(self, rs: dict, main_pid=None, memory_unit: DataUnit = None):
        # 这部分性能读取有一定延时，需在线程中运行，否则会应用主进程计时的准确性
        now = time.time()
        if self.main_process_only:
            if not main_pid:
                raise ValueError('当前测试内容为针对App主进程测试，请在`on_start_cpu_memory_test`函数中返回主进程id')
            memory = self.get_memory_usage(main_pid, unit=memory_unit)
            curr_g, curr_a = self.get_cpu_usage(main_pid)
        else:
            pl = self.adb.find_process_ids(self.app.pkg)
            # App运行时可能会启动很多进程，每次测试之前重新读一次进程列表
            memory = self.get_memory_usage(pid_list=pl, unit=memory_unit)
            curr_g, curr_a = self.get_cpu_usage(pid_list=pl)
        logging.debug(f'Time cost(ms)\ncpu-system: {curr_g.cost_ms}\n'
                      f'cpu-app: {curr_a.cost_ms}\nmemory: {memory.cost_ms}')
        rs[int(now * 1000)] = {'cpu_g': curr_g, 'cpu_a': curr_a, 'memory': memory.total_pss}

    @abc.abstractmethod
    def on_start_cpu_memory_test(self) -> str:
        """当即将开始CPU，内存测试时执行以下操作：[启动待测App]
        若测试的内容是针对主进程的，则必须在此函数返回启动后的待测App的主进程
        参考：
        # self.adb.start_app(self.app)
        # while True:
        #     time.sleep(0.008)
        #     try:
        #         return self.adb.find_main_process_id(self.app.pkg)
        #         break
        #     except ValueError as e:
        #         logging.warning(f'重试获取{self.app.pkg}主进程id...')
        """
        raise NotImplementedError

    def start_test_cpu_memory(self, min_wait_seconds: int = 10, max_listen_seconds: int = 60) -> dict:
        assert self.app
        logging.info(f'即将在 <{self.app}>\'上的 '
                     f'[{self.main_process_only and "主" or "所有"}] '
                     f'进程测试 CPU/Memory 持续监听最多 [{max_listen_seconds}] 秒...')
        data = dict(timestamp=time.time(), cpu=[], memory=[], keep=True)
        tmp_data = {
            int(time.time() * 1000): {'cpu_g': self.adb.get_cpu_global(), 'cpu_a': AppCPU(0, 0, 0), 'memory': 0}
            # 多线程执行每一秒的性能数据读取，但是每个线程执行过程中可能会出现失败而进行重试读取，有一定延时现象，因此需要以该线程第一次读取发起读取的时间作为键，保证数据的正确先后顺序
            # 获取未启动应用时的系统CPU使用时间，将目标App CPU使用时间初始为0
        }
        main_pid = self.on_start_cpu_memory_test()
        for i in range(max_listen_seconds):
            if not data['keep']:
                break
            # 1秒读一次数据，耗时操作放在线程中执行，以确保读取数据的操作为每秒执行一次
            time.sleep(1)
            self._th_pool.putRequest(WorkRequest(self._async_run_get_cpu_memory, args=(main_pid, tmp_data, MB)))
            self._th_pool.putRequest(WorkRequest(self._async_on_test_cpu_memory, args=(i, max_listen_seconds,
                                                                                       min_wait_seconds,
                                                                                       tmp_data, data)))
        self._th_pool.wait()
        return data

    @abc.abstractmethod
    def on_start_test_netflow(self):
        # 在开启流量监听后执行的内容
        raise NotImplementedError

    def start_test_netflow(self, listen_seconds: int = 10) -> dict:
        assert self.app
        logging.info(f'即将对 <{self.app}> 进行流量监测，持续 [{listen_seconds}] 秒...')
        data = dict(timestamp=time.time(), net_up=[], net_down=[])
        self.adb.prepare_and_start_statistics_net_traffic(self.app)
        self.adb.go_back()
        time.sleep(0.1)
        self.on_start_test_netflow()
        time.sleep(listen_seconds)
        net = self.adb.finish2format_statistics_net_traffic()
        for n in net:
            data['net_up'].append(n['up'])
            data['net_down'].append(n['down'])
        return data

    @abc.abstractmethod
    def on_start_screen_record(self):
        # 成功调起录屏后的操作
        raise NotImplementedError

    @abc.abstractmethod
    def apply_screen_record_permission(self) -> bool:
        """对录屏权限的操作 涉及到UI
        :return 是否授权成功
        """
        raise NotImplementedError

    def start_screen_record(self, key: str = None, record_wait_seconds=0):
        # 如果录屏后马上上传，会影响手机的性能，建议先进行录屏，再进行上传，以提高整体运行效率。
        assert self.app
        if record_wait_seconds:
            self.adb.update_screen_record_settings(
                auto_stop_record=True, record_count_down_second=record_wait_seconds)
        else:
            self.adb.update_screen_record_settings(
                auto_stop_record=False
            )
        self.adb.start_screen_record(key)
        time.sleep(0.5)  # 等待工具响应
        if self.apply_screen_record_permission():
            self.on_start_screen_record()  # 这里涉及到UI的操作，延时可能比较长，不通UI框架延时不同
            if record_wait_seconds:
                time.sleep(record_wait_seconds)

    def stop_screen_record(self):
        # 如果没有设置自动停止录屏，需手动调用停止录屏
        self.adb.stop_screen_record()
