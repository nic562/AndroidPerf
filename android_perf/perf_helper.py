import os
import abc
import time
import datetime
from decimal import Decimal
from threadpool import ThreadPool, WorkRequest

from .cpu import SysCPU, AppCPU
from .data_unit import DataUnit, KB, MB
from .adb_with_tools import AdbProxyWithScreenRecorder, AppInfo
from .log import default as logging


class AppPerfBaseHelper(metaclass=abc.ABCMeta):
    app: AppInfo

    def __init__(self, adb: AdbProxyWithScreenRecorder, main_process_only=False):
        self.adb = adb
        self.main_process_only = main_process_only
        self._th_pool = ThreadPool(21)
        self.app = None

    @staticmethod
    def second2str(seconds: float) -> str:
        if seconds > 3600:
            return '%d时%d分%d秒' % (seconds // 3600.0, seconds % 3600 // 60.0, seconds % 60)
        return '%d分%d秒' % (seconds // 60.0, seconds % 60)

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

    @staticmethod
    def decimal_format(d, fm=Decimal('0.00')):
        return Decimal(str(d)).quantize(fm)

    def exit(self, kill_tools=True, kill_process=True):
        try:
            self.adb.close(kill_tools=kill_tools)
        except Exception as e:
            logging.error("Close Adb error:\n\n%s", e)
        finally:
            if kill_process:
                os._exit(0)

    @abc.abstractmethod
    def before_test(self):
        raise NotImplementedError

    @abc.abstractmethod
    def on_test_cpu_memory(self, current_second: int, max_listen_seconds: int, data: dict):
        # 每秒读取CPU、内存数据时干的事
        raise NotImplementedError

    def _async_on_test_cpu_memory(self, current_second: int, max_listen_seconds: int, min_wait_seconds: int,
                                  raw_data: dict, data: dict):
        logging.debug(f'{datetime.datetime.now()} On Test {current_second}th second!')
        if len(raw_data) < min_wait_seconds:
            # 取数少于n秒的不进行后续操作
            return
        self.on_test_cpu_memory(current_second, max_listen_seconds, self._compute_cpu_memory(raw_data, data))

    def _compute_cpu_memory(self, raw_data: dict, data: dict):
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

    def _async_run_get_cpu_memory(self, main_pid, rs: dict, memory_unit: DataUnit = None):
        # 这部分性能读取有一定延时，需在线程中运行，否则会应用主进程计时的准确性
        now = time.time()
        if self.main_process_only:
            memory = self.get_memory_usage(main_pid, unit=memory_unit)
            curr_g, curr_a = self.get_cpu_usage(main_pid)
        else:
            pl = self.adb.find_process_ids(self.app.pkg)
            # App运行时可能会启动很多进程，每次测试之前重新读一次进程列表
            memory = self.get_memory_usage(pid_list=pl, unit=memory_unit)
            curr_g, curr_a = self.get_cpu_usage(pid_list=pl)
        logging.debug(f'cost(ms): cpu-system# {curr_g.cost_ms}; cpu-app# {curr_a.cost_ms}; memory# {memory.cost_ms}')
        rs[int(now * 1000)] = {'cpu_g': curr_g, 'cpu_a': curr_a, 'memory': memory.total_pss}

    def start_test_cpu_memory(self, min_wait_seconds: int = 10, max_listen_seconds: int = 60) -> dict:
        assert self.app
        logging.info(f'即将在 <{self.app}>\'上的 '
                     f'[{self.main_process_only and "主" or "所有"}] '
                     f'进程测试 CPU/Memory 持续监听最多 [{max_listen_seconds}] 秒...')
        data = dict(timestamp=time.time(), cpu=[], memory=[], keep=True)
        self.before_test()
        tmp_data = {
            int(time.time() * 1000): {'cpu_g': self.adb.get_cpu_global(), 'cpu_a': AppCPU(0, 0, 0), 'memory': 0}
            # 多线程执行每一秒的性能数据读取，但是每个线程执行过程中可能会出现失败而进行重试读取，有一定延时现象，因此需要以该线程第一次读取发起读取的时间作为键，保证数据的正确先后顺序
            # 获取未启动应用时的系统CPU使用时间，将目标App CPU使用时间初始为0
        }
        self.adb.start_app(self.app)
        while True:
            time.sleep(0.008)
            try:
                main_pid = self.adb.find_main_process_id(self.app.pkg)
                break
            except ValueError as e:
                logging.warning(f'重试获取{self.app.pkg}主进程id...')
        for i in range(max_listen_seconds):
            if not data['keep']:
                break
            # 1秒读一次数据
            time.sleep(1)
            self._th_pool.putRequest(WorkRequest(self._async_run_get_cpu_memory, args=(main_pid, tmp_data, MB)))
            self._th_pool.putRequest(WorkRequest(self._async_on_test_cpu_memory, args=(i, max_listen_seconds,
                                                                                       min_wait_seconds,
                                                                                       tmp_data, data)))
        self._th_pool.wait()
        self.after_test()
        return data

    @abc.abstractmethod
    def on_start_test_netflow(self):
        raise NotImplementedError

    @abc.abstractmethod
    def checking_netflow_is_ready(self, max_check_second=60, netflow_threshold=1) -> bool:
        raise NotImplementedError

    def start_test_netflow(self, max_check_second=60, listen_seconds: int = 10, netflow_threshold=1) -> dict:
        assert self.app
        logging.info(f'即将对 <{self.app}> 进行流程监测'
                     f' [{listen_seconds}] 秒...')
        data = dict(timestamp=time.time(), net_up=[], net_down=[])
        self.before_test()
        self.adb.start_app(self.app)
        if not self.checking_netflow_is_ready(max_check_second, netflow_threshold):
            return
        pid = self.adb.find_main_process_id(self.app.pkg)
        latest = self.adb.get_process_traffic(pid)
        self.on_start_test_netflow()
        for _ in range(listen_seconds):
            time.sleep(1)
            new = self.adb.get_process_traffic(pid)
            tmp = self.adb.compute_traffic_increase(latest, new, unit=KB)
            data['net_up'].append(tmp.tx_total)
            data['net_down'].append(tmp.rx_total)
        self.after_test()
        return data

    @abc.abstractmethod
    def on_start_screen_record(self):
        raise NotImplementedError

    @abc.abstractmethod
    def permission_screen_record(self):
        raise NotImplementedError

    def start_screen_record(self, key: str = None, record_wait_seconds=5):
        # 如果录屏后马上上传，会影响手机的性能，建议先进行录屏，再进行上传，以提高整体运行效率。
        assert self.app
        self.before_test()
        self.adb.start_app(self.app)
        time.sleep(10)
        self.adb.start_record_screen(key)
        time.sleep(0.5)
        if self.permission_screen_record():
            self.on_start_screen_record()
            time.sleep(record_wait_seconds)
        self.after_test()

    def after_test(self):
        self.adb.kill_by_app(self.app)
