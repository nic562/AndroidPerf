from abc import ABCMeta
import re
import time

from .abstract_adb import AdbInterface
from .data_unit import DataUnit, BYTE


class NetTraffic:
    """
    mobile: 12345G 移动流量
    wifi: 网关流量
    rx: 接收流量
    tx: 发送流量
    cost_ms: 指令数据获取所消耗时间，毫秒
    """
    mobile_total: float = 0
    wifi_total: float = 0
    rx_total: float = 0
    tx_total: float = 0

    def __init__(self, unit: DataUnit = None):
        self.mobile_rx_byte = 0
        self.mobile_tx_byte = 0
        self.wifi_rx_byte = 0
        self.wifi_tx_byte = 0
        self.cost_ms = 0
        self.unit = unit or BYTE

    def number_format(self, v) -> float:
        return self.unit.format(v)

    def compute_total(self):
        self.mobile_total = self.number_format(self.mobile_rx_byte + self.mobile_tx_byte)
        self.wifi_total = self.number_format(self.wifi_rx_byte + self.wifi_tx_byte)
        self.rx_total = self.number_format(self.mobile_rx_byte + self.wifi_rx_byte)
        self.tx_total = self.number_format(self.mobile_tx_byte + self.wifi_tx_byte)
        return self

    def __str__(self):
        return f'NetTraffic Unit: {self.unit}\nCost(ms): {self.cost_ms}\n' \
               f'Mobile Total: {self.mobile_total}\nWifi Total: {self.wifi_total}\n' \
               f'Receive Total: {self.rx_total}\nSent Total: {self.tx_total}'


class TrafficAdb(AdbInterface, metaclass=ABCMeta):
    _net_files = ['tcp', 'tcp6', 'udp', 'udp6']

    def _get_net_flow_raw(self, uid: str, target_net_file: str):
        """
        读取 tcp 或 udp 流量统计
        兼容性不好，某些Android版本中，这些文件已经不存在，或者无权限读取
        :param uid:
        :param target_net_file: 参考 _net_files
        :return:
        """
        # 状态字参考:https://users.cs.northwestern.edu/~agupta/cs340/project2/TCPIP_State_Transition_Diagram.pdf
        # https://guanjunjian.github.io/2017/11/09/study-8-proc-net-tcp-analysis/
        # https://zhuanlan.zhihu.com/p/49981590
        rs = self.run_shell(f'cat /proc/net/{target_net_file} | grep {uid}')
        if rs:
            ll = []
            for r in rs.split('\n'):
                if not r:
                    continue
                m = re.split(r'\s+', r.strip())
                if m and m[7] == uid:
                    ll.append(m)
            return ll

    @staticmethod
    def _traffic_parse_line(rs: str):
        # 原始数据的每一行，第2个信息为接收流量，第10个信息为发送流量
        items = rs.split()
        return int(items[1]), int(items[9])

    def _traffic_parse(self, rs: str, start_ms: int, unit: DataUnit = None):
        if rs.find('No such') != -1:
            # 进程有可能被销毁
            raise KeyError(f'Bad return: {rs}')
        if rs.find('error') != -1:
            raise ValueError(f'Error return: {rs}')
        end_ms = int(time.time() * 1000)
        info = NetTraffic(unit=unit)
        info.cost_ms = end_ms - start_ms
        for line in rs.split('\n'):
            if 'wlan0' in line:
                # wifi 流量
                info.wifi_rx_byte, info.wifi_tx_byte = self._traffic_parse_line(line)
            elif 'rmnet0' in line:
                info.mobile_rx_byte, info.mobile_tx_byte = self._traffic_parse_line(line)
        return info.compute_total()

    def get_device_traffic(self, unit: DataUnit = None) -> NetTraffic:
        """获取设备整机流量统计
        注意：该数据为设备启动（重启后归0）后开始累计的
        """
        _t = int(time.time() * 1000)
        rs = self.run_shell('cat /proc/net/dev', clean_wrap=True)
        return self._traffic_parse(rs, _t, unit=unit)

    def get_process_traffic(self, pid, unit: DataUnit = None) -> NetTraffic:
        """
        注意：仅获取主进程则可表示整个App的流量
        获取具体进程所属App的流量统计，结果是从设备启动开始开始的累计值
        虽然进程文件在进程销毁后就删掉，但是所属应用的流量统计并不清0
        """
        _t = int(time.time() * 1000)
        rs = self.run_shell(f'cat /proc/{pid}/net/dev', clean_wrap=True)
        return self._traffic_parse(rs, _t, unit=unit)

    @staticmethod
    def compute_traffic_increase(start_traffic: NetTraffic, end_traffic: NetTraffic,
                                 unit: DataUnit = None) -> NetTraffic:
        rs = NetTraffic(unit)
        rs.unit = end_traffic.unit
        rs.cost_ms = start_traffic.cost_ms + end_traffic.cost_ms
        rs.wifi_rx_byte = end_traffic.wifi_rx_byte - start_traffic.wifi_rx_byte
        rs.wifi_tx_byte = end_traffic.wifi_tx_byte - start_traffic.wifi_tx_byte
        rs.mobile_rx_byte = end_traffic.mobile_rx_byte - start_traffic.mobile_rx_byte
        rs.mobile_tx_byte = end_traffic.mobile_tx_byte - start_traffic.mobile_tx_byte
        return rs.compute_total()
