from abc import ABCMeta
import re
import time

from .abstract_adb import AdbInterface
from .log import default as logging
from .data_unit import DataUnit, KB


class MemoryInfo:
    RE_PROCESS = re.compile(r'\*\* MEMINFO in pid (\d+) \[(\S+)] \*\*')
    RE_TOTAL_PSS = re.compile(r'TOTAL PSS:\s+(\d+)')
    RE_JAVA_HEAP = re.compile(r"Java Heap:\s+(\d+)")
    RE_NATIVE_HEAP = re.compile(r"Native Heap:\s+(\d+)")
    RE_SYSTEM = re.compile(r"System:\s+(\d+)")

    def __init__(self, unit: DataUnit = KB):
        self.pid = -1
        self.process_name = ''
        self.total_pss = 0
        self.java_heap = 0
        self.native_heap = 0
        self.system = 0
        self.cost_ms = 0
        self.unit = unit

    def number_format(self, num_str: str) -> float:
        return self.unit.format(float(num_str))

    def parse(self, rs: str, start_ms: int):
        end_ms = int(time.time() * 1000)
        match = self.RE_PROCESS.search(rs)
        self.pid = match.group(1)
        self.process_name = match.group(2)
        self.total_pss = self.number_format(self.RE_TOTAL_PSS.findall(rs)[0])
        self.java_heap = self.number_format(self.RE_JAVA_HEAP.findall(rs)[0])
        self.native_heap = self.number_format(self.RE_NATIVE_HEAP.findall(rs)[0])
        self.system = self.number_format(self.RE_SYSTEM.findall(rs)[0])
        self.cost_ms = end_ms - start_ms
        return self

    def __str__(self):
        return f'MemoryInfo Unit: {self.unit}\nCost(ms): {self.cost_ms}\n' \
               f'Pid: {self.pid}\nProcess: {self.process_name}\n' \
               f'Total: {self.total_pss}\nJavaHeap: {self.java_heap}\n' \
               f'NativeHeap: {self.native_heap}\nSystem: {self.system}'


class DeviceMemoryInfo:
    RE_ALL = re.compile(r'Mem:\s+(\d+)\s+(\d+)\s+(\d+)')

    def __init__(self, unit: DataUnit = KB):
        self.total = 0
        self.used = 0
        self.free = 0
        self.cost_ms = 0
        self.unit = unit

    def parse(self, rs: str, start_ms: int):
        end_ms = int(time.time() * 1000)
        match = self.RE_ALL.search(rs)
        self.total = match.group(1)
        self.used = match.group(2)
        self.free = match.group(3)
        self.cost_ms = end_ms - start_ms
        return self

    def __str__(self):
        return f'Unit: {self.unit}\nCost(ms): {self.cost_ms}\nTotal: {self.total}\nUsed: {self.used}\nFree: {self.free}'


class MemoryAdb(AdbInterface, metaclass=ABCMeta):

    def get_device_memory_details(self, unit: DataUnit):
        """获取设备内存数据详情"""
        return self.run_shell(f'free -{unit.flag}')

    def get_device_memory(self, unit: DataUnit = KB) -> DeviceMemoryInfo:
        _t = int(time.time() * 1000)
        rs = self.get_device_memory_details(unit)
        return DeviceMemoryInfo(unit).parse(rs, _t)

    def get_process_memory_details(self, app_bundle_or_pid: str):
        """
        :param app_bundle_or_pid: 包名或者进程ID，若指定包名时，仅能获取主进程的内存数据
        """
        return self.run_shell(f'dumpsys meminfo {app_bundle_or_pid}')

    def get_process_memory(self, app_bundle_or_pid: str) -> MemoryInfo:
        _t = int(time.time() * 1000)
        rs = self.get_process_memory_details(app_bundle_or_pid)
        if rs.find('No process') != -1:
            # 进程被销毁
            logging.warning(f'process miss:{app_bundle_or_pid}')
            return
        if rs.find('MEMINFO in pid') == -1:
            logging.warning('try to get MemoryInfo again!')
            return self.get_process_memory(app_bundle_or_pid)
        return MemoryInfo().parse(rs, _t)

    def get_processes_memory(self, process_id_list: list) -> MemoryInfo:
        # 返回的 MemoryInfo 中进程信息为第一个进程的信息
        total: MemoryInfo = None
        for pi in process_id_list:
            m = self.get_process_memory(pi)
            if total:
                total.total_pss += m.total_pss
                total.java_heap += m.java_heap
                total.native_heap += m.native_heap
                total.system += m.system
                total.cost_ms += m.cost_ms
            else:
                total = m
        return total
