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
from .whistle import active_statistics_status, update_statistics_settings


class AndroidPerfBaseHelper(metaclass=abc.ABCMeta):

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

    def launch_app(self):
        assert self.app
        logging.info(f'启动{self.app}')
        self.adb.start_app(self.app)

    def kill_app(self):
        assert self.app
        logging.info(f'杀掉{self.app}')
        self.adb.kill_by_app(self.app)

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
        """调用 start_test_cpu_memory后，在min_wait_seconds之后，每秒读取CPU、内存数据后要执行的操作。
        # 注意这里可能会在多个线程中执行(请做好状态同步)，执行耗时太长的操作会一直占用线程池资源。
        另外，可通过 data['keep'] = True/False 来控制继续读取CPU，内存性能数据
        """
        raise NotImplementedError

    def _async_on_test_cpu_memory(self, current_second: int, max_listen_seconds: int, min_wait_seconds: int,
                                  raw_data: dict, data: dict):
        logging.debug(f'{datetime.datetime.now()} On Test {current_second}th second!')
        if len(raw_data) < min_wait_seconds:
            # 取数少于n秒的不进行后续操作
            return
        self.on_test_cpu_memory(current_second, max_listen_seconds, self._compute_cpu_memory(raw_data, data))

    @staticmethod
    def _check_cpu_memory_data(idx: int, d: dict) -> bool:
        ok = True
        for k, v in d.items():
            if v is None:
                logging.debug(f'第{idx}秒 {k}数据未完成采集！')
                ok = False
        return ok

    def _compute_cpu_memory(self, raw_data: dict, data: dict):
        # 多个线程读取性能数据，计算时需重新按时序排列
        sort_data = sorted(raw_data.items(), key=lambda x: x[0])
        cpu_list = []
        memory_list = []
        for idx, d in enumerate(sort_data):
            if idx == 0:
                continue
            f_d = sort_data[idx - 1][1]
            if not self._check_cpu_memory_data(idx - 1, f_d):
                continue
            _d = d[1]
            if not self._check_cpu_memory_data(idx, _d):
                continue
            cpu, _ = self.adb.compute_cpu_rate(f_d['cpu_g'], _d['cpu_g'], f_d['cpu_a'], _d['cpu_a'])
            memory = _d['memory'].total_pss
            logging.debug('current CPU:[%.2f], MEM:[%.2f]', cpu * 100, memory)
            cpu_list.append(cpu)
            memory_list.append(memory)
        data['cpu'] = cpu_list
        data['memory'] = memory_list
        return data

    def _async_run_get_cpu(self, rs: dict, main_pid=None, pid_list=None):
        assert main_pid or pid_list
        # 这部分性能读取有一定延时，需在线程中运行，否则会应用主进程计时的准确性
        if self.main_process_only:
            if not main_pid:
                raise ValueError('当前测试内容为针对App主进程测试，请在`on_start_cpu_memory_test`函数中返回主进程id')
            curr_g, curr_a = self.get_cpu_usage(main_pid)
        else:
            curr_g, curr_a = self.get_cpu_usage(pid_list=pid_list)
        logging.debug(f'System CPU:\n{curr_g}')
        logging.debug(f'App CPU:\n{curr_a}')
        rs['cpu_g'] = curr_g
        rs['cpu_a'] = curr_a

    def _async_run_get_memory(self, rs: dict, main_pid=None, pid_list=None, unit: DataUnit = None):
        assert main_pid or pid_list
        # 这部分性能读取有一定延时，需在线程中运行，否则会应用主进程计时的准确性
        if self.main_process_only:
            if not main_pid:
                raise ValueError('当前测试内容为针对App主进程测试，请在`on_start_cpu_memory_test`函数中返回主进程id')
            memory = self.get_memory_usage(main_pid, unit=unit)
        else:
            memory = self.get_memory_usage(pid_list=pid_list, unit=unit)
        logging.debug(f'App Memory:\n{memory}')
        rs['memory'] = memory

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
        #     except ValueError as e:
        #         logging.warning(f'重试获取{self.app.pkg}主进程id...')
        """
        raise NotImplementedError

    def _work_on_cpu_memory(self, final_data: dict, tmp_data: dict, idx: int, main_pid=None,
                            min_wait_seconds: int = 0, max_listen_seconds: int = 60):
        # App运行时可能会启动很多进程，每次测试之前重新读一次进程列表
        idx_data = {'cpu_g': None, 'cpu_a': None, 'memory': None}
        tmp_data[idx + 1] = idx_data
        pl = main_pid is None and self.adb.find_process_ids(self.app.pkg) or None
        self._th_pool.putRequest(WorkRequest(self._async_run_get_cpu, args=(idx_data, main_pid, pl)))
        self._th_pool.putRequest(WorkRequest(self._async_run_get_memory, args=(idx_data, main_pid, pl, MB)))
        self._th_pool.putRequest(WorkRequest(self._async_on_test_cpu_memory, args=(idx, max_listen_seconds,
                                                                                   min_wait_seconds,
                                                                                   tmp_data, final_data)))

    def start_test_cpu_memory(self, min_wait_seconds: int = 0, max_listen_seconds: int = 60) -> dict:
        assert self.app
        logging.info(f'即将在 <{self.app}>\'上的 '
                     f'[{self.main_process_only and "主" or "所有"}] '
                     f'进程测试 CPU/Memory 持续监听最多 [{max_listen_seconds}] 秒...')
        data = dict(timestamp=time.time(), cpu=[], memory=[], keep=True)
        tmp_data = {
            0: {'cpu_g': self.adb.get_cpu_global(), 'cpu_a': AppCPU(0, 0, 0), 'memory': 0}
            # 多线程执行每一秒的性能数据读取，但是每个线程执行过程中可能会出现失败而进行重试读取，有一定延时现象，因此需要以该线程第一次读取发起读取的时间作为键，保证数据的正确先后顺序
            # 获取未启动应用时的系统CPU使用时间，将目标App CPU使用时间初始为0
        }
        main_pid = self.on_start_cpu_memory_test()
        for i in range(max_listen_seconds):
            if not data['keep']:
                break
            # 1秒读一次数据，耗时操作放在线程中执行，以确保读取数据的操作为每秒执行一次
            time.sleep(1)
            self._th_pool.putRequest(WorkRequest(self._work_on_cpu_memory, args=(
                data, tmp_data, i, main_pid, min_wait_seconds, max_listen_seconds
            )))
        self._th_pool.wait()
        # 等待所有线程结束
        return data

    @abc.abstractmethod
    def on_start_test_netflow(self):
        # 在开启流量监听后执行的内容
        raise NotImplementedError

    def start_test_netflow(self, listen_seconds: int = 10) -> dict:
        assert self.app
        data = dict(timestamp=time.time(), net_up=[], net_down=[])
        self.adb.prepare_and_start_statistics_net_traffic(self.app)
        logging.info(f'开始对 <{self.app}> 进行流量监测，持续 [{listen_seconds}] 秒...')
        self.adb.go_back()
        time.sleep(0.1)
        self.on_start_test_netflow()
        time.sleep(listen_seconds)
        net = self.adb.finish2format_statistics_net_traffic()
        net = net[-listen_seconds:]
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

    def start_screen_record(self, key: str = None, record_wait_seconds=0, auto_delete=True):
        """
        开启录屏
        :param key: 视频唯一表示，方便查找对其进行特定操作，例如指定要上传特定的视频。可空。
        :param record_wait_seconds: 自动录屏停止时间，默认为0则不自动停止
        :param auto_delete: 设置工具，完成上传后自动删除视频
        :return:
        """
        # 如果录屏后马上上传，会影响手机的性能，建议先进行录屏，再进行上传，以提高整体运行效率。
        assert self.app
        if record_wait_seconds:
            self.adb.update_screen_record_settings(
                auto_stop_record=True, record_count_down_second=record_wait_seconds,
                record_auto_delete=auto_delete
            )
        else:
            self.adb.update_screen_record_settings(
                auto_stop_record=False,
                record_auto_delete=auto_delete
            )
        self.adb.start_screen_record(key)
        time.sleep(0.5)  # 等待工具响应
        if self.apply_screen_record_permission():
            logging.info('录屏授权完成且成功开启录屏！')
            self.on_start_screen_record()  # 这里涉及到UI的操作，延时可能比较长，不通UI框架延时不同
            if record_wait_seconds:
                time.sleep(record_wait_seconds)

    def stop_screen_record(self):
        # 如果没有设置自动停止录屏，需手动调用停止录屏
        self.adb.stop_screen_record()
        logging.info('结束录屏！')

    def check_app_netflow_in_threshold(self, max_check_second=60, rx_byte_threshold=1,
                                       tx_byte_threshold=1, limit_seconds=5) -> bool:
        """
        检测应用流量状态是否符合阈值
        :param max_check_second: 最大检测时间，秒
        :param rx_byte_threshold: 每秒下载字节数阈值
        :param tx_byte_threshold: 每秒上传字节数阈值
        :param limit_seconds: 保持不大于阈值最少持续时长，秒
        :return: bool. 是否符合阈值要求
        """
        assert self.app
        logging.info(f'{self.app}即将进入流量状态检测，等待收发流量低于阈值...')
        self.adb.prepare_and_start_statistics_net_traffic(self.app)
        time.sleep(0.05)
        self.adb.go_back()
        try:
            latest = None
            for i in range(max_check_second):
                # 最多持续检测n秒，每1秒读一次数据
                time.sleep(1)
                latest = self.adb.read_current_net_traffic()
                if len(latest) < limit_seconds:
                    continue
                ready = 0
                for j in range(limit_seconds):
                    line = latest[-j - 1]
                    ok = line['up'] < tx_byte_threshold and line['down'] < rx_byte_threshold
                    if ok:
                        ready += 1
                if ready == limit_seconds:
                    logging.info(f'在{i + 1}秒后，设备连续{limit_seconds}秒'
                                 f'接收流量小于{rx_byte_threshold}byte/s，发送流量小于{tx_byte_threshold}byte/s')
                    return True

            logging.warning(f'{max_check_second}秒后，{self.app}'
                            f'最近{limit_seconds}秒，接收流量仍然大于{rx_byte_threshold}byte/s，或发送流量仍然大于{tx_byte_threshold}byte/s。'
                            f'流量检测无法通过，请校对检测结果与阈值\n')
            for x in latest:
                logging.warning(x)
            return False
        finally:
            self.adb.stop_statistics_net_traffic()

    def check_device_netflow_in_threshold(self, max_check_second=60, rx_byte_threshold=1,
                                          tx_byte_threshold=1, limit_seconds=5) -> bool:
        """
        检测设备流量状态是否符合阈值
        :param max_check_second: 最大检测时间，秒
        :param rx_byte_threshold: 每秒下载字节数阈值
        :param tx_byte_threshold: 每秒上传字节数阈值
        :param limit_seconds: 保持不大于阈值最少持续时长，秒
        :return: bool. 是否符合阈值要求
        """
        logging.info(f'即将进入设备整机流量状态检测，等待收发流量低于阈值...')
        traffics = []
        latest = self.adb.get_device_traffic()
        for i in range(max_check_second):
            time.sleep(1)
            new = self.adb.get_device_traffic()
            _tmp = self.adb.compute_traffic_increase(latest, new)
            latest = new
            logging.debug(f'第[{i + 1}]秒，发送流量{_tmp.tx_total / 1024} kb/s. 接收流量{_tmp.rx_total / 1024} kb/s')
            traffics.append(_tmp)
            if len(traffics) >= limit_seconds:
                ok = True
                for j in range(limit_seconds):
                    _t = traffics[-j - 1]
                    if _t.rx_total > rx_byte_threshold or _t.tx_total > tx_byte_threshold:
                        ok = False
                        break
                if ok:
                    logging.info(f'在{i + 1}秒后，设备连续{limit_seconds}秒'
                                 f'接收流量小于{rx_byte_threshold}byte/s，发送流量小于{tx_byte_threshold}byte/s')
                    return True
        logging.warning(f'{max_check_second}秒后，设备'
                        f'接收流量仍然大于{rx_byte_threshold}byte/s，发送流量仍然大于{tx_byte_threshold}byte/s。'
                        f'流量检测无法通过，请校对检测结果与阈值\n')
        for x in traffics:
            logging.warning(x)
        return False


class AndroidPerfBaseHelperWithWhistle(AndroidPerfBaseHelper, metaclass=abc.ABCMeta):
    # 实现基于whistle 和 whistle.statistics插件的http/https 网络请求统计

    def __init__(self, adb: AdbProxyWithToolsAll, whistle_address: str, main_process_only=False):
        super().__init__(adb, main_process_only)
        self.whistle_address = whistle_address
        assert self.whistle_address

    @abc.abstractmethod
    def get_whistle_statistics_settings(self) -> str:
        # 获取 whistle.statistics插件的配置，参考https://github.com/nic562/whistle.statistics
        raise NotImplementedError

    @abc.abstractmethod
    def on_start_test_req_count(self):
        # 在进行网络接口统计开始时执行的操作
        raise NotImplementedError

    def start_test_req_count(self, listen_seconds: int = 10, checking_app_threshold_before_start=True,
                             device_rx_byte_threshold=1,
                             device_tx_byte_threshold=1,
                             max_app_threshold_checking_second=60,
                             limit_app_threshold_keep_second=5):
        """
        开始http/https网络请求统计
        :param listen_seconds: 统计时长，秒，如果指定大于0 的值，则按照统计时间自动停止，否则需要手动调用 stop_test_req_count进行关闭
        :param checking_app_threshold_before_start: 执行 on_start_test_req_count 前是否检查App流量状态
        :param device_rx_byte_threshold:  设备接收流量阈值，如果开始前要检查App流量状态，将按此阈值判断接收流量
        :param device_tx_byte_threshold:  设备发送流量阈值，如果开始前要检查App流量状态，将按此阈值判断发送流量
        :param max_app_threshold_checking_second:  检查流量状态，最长检查时间
        :param limit_app_threshold_keep_second: App流量保持阈值状态持续最少秒数
        :return: 无。因为数据将通过whistle服务进行统计和上传，所以这里并无返回值
        """
        assert self.app
        logging.info(f'即将对 <{self.app}> 进行网络请求接口监测'
                     f' [{listen_seconds}] 秒...')
        if checking_app_threshold_before_start and not self.check_app_netflow_in_threshold(
                max_app_threshold_checking_second, device_rx_byte_threshold, device_tx_byte_threshold,
                limit_seconds=limit_app_threshold_keep_second):
            # 等待设备流量低于阈值再开始抓包
            return
        time.sleep(0.05)
        logging.info(f'正在配置手机代理服务地址({self.whistle_address})...')
        self.adb.set_http_proxy(self.whistle_address)
        is_error = False
        try:
            update_statistics_settings(
                self.whistle_address,
                self.get_whistle_statistics_settings(),
                auto_stop=listen_seconds > 0,
                timeout=listen_seconds
            )  # 配置抓包上传数据，开启10秒后自动关闭抓包
            active_statistics_status(self.whistle_address)  # 激活
            self.on_start_test_req_count()
            if listen_seconds:
                time.sleep(listen_seconds + 5)  # 等待足够的时间
        except:
            # 出现任何异常时，也要保证清理代理服务环境
            is_error = True
            raise
        finally:
            if is_error or listen_seconds:
                # 如果是设置自动停止的 或者发生异常时，则自动清理环境
                self.reset_whistle_server_and_close_device_http_proxy()

    def stop_test_req_count(self):
        try:
            active_statistics_status(self.whistle_address, active=False)  # 关闭
        finally:
            self.reset_whistle_server_and_close_device_http_proxy()

    def reset_whistle_server_and_close_device_http_proxy(self):
        # 自动清理whistle配置以及
        try:
            update_statistics_settings(self.whistle_address, '')
        finally:
            self.adb.close_http_proxy()
            logging.info('已清理手机代理服务配置！')
