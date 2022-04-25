from abc import ABCMeta
import re

from .abstract_adb import AdbInterface
from .log import default as logging


class CPUUsageBase:
    def __init__(self, user: int, kernel: int):
        """
        :param user: 用户态时间
        :param kernel: 内核态时间
        """
        self.user = user
        self.kernel = kernel

    def __str__(self):
        return f'CPU User: {self.user}, Kernel: {self.kernel}'


class AppCPU(CPUUsageBase):
    def __str__(self):
        return f'[App]{super().__str__()}'


class SysCPU(CPUUsageBase):
    def __init__(self, user: int, kernel: int, total: int, freq: float):
        """
        :param total: 总的CPU时间
        :param freq: CPU 当前频率占最大频率比例
        """
        super().__init__(user, kernel)
        self.total = total
        self.freq = freq

    def __str__(self):
        return f'[Sys]{super().__str__()}'


class CPUUsageAdb(AdbInterface, metaclass=ABCMeta):
    __cpu_scaling_max_freq_enable = True

    def get_cpu_count(self) -> int:
        c = self.run_shell('cat /proc/cpuinfo | grep ^processor | wc -l')
        return int(c)

    def get_cpu_x_curr_freq(self, idx: int) -> int:
        """获取某个CPU核的当前频率
        /sys/devices/system/cpu/cpu{x}/cpufreq/ 目录下，cpuinfo_cur_freq 和 scaling_cur_freq 均有记录该CPU的当前频率，
        不同的是，cpuinfo_cur_freq 代表的是CPU硬件层面支持的频率； scaling_cur_freq 是指在当前工作模式（可变，例如：省电、高性能等）下的实际工作频率
        :param idx: CPU核的下标
        """
        f = self.run_shell(f'cat /sys/devices/system/cpu/cpu{idx}/cpufreq/scaling_cur_freq')
        return int(f)

    def get_cpu_x_max_freq(self, idx: int) -> int:
        """获取某个CPU核的最大频率
        /sys/devices/system/cpu/cpu{x}/cpufreq/ 目录下，cpuinfo_max_freq 和 scaling_max_freq 均有记录该CPU的最高频率，
        不同的是，cpuinfo_max_freq 代表的是CPU硬件层面支持的最高频率； scaling_max_freq 是指在当前工作模式下限制的最高工作频率
        注意：如果读取文件 提示 Permission denied 权限不足，该文件部分在设备中的权限可能被锁定，
        请尝试关闭手机的 USB 调试，和开发者模式，重启手机，再重新开启开发者以及USB调试
        :param idx: CPU核的下标
        """
        if self.__cpu_scaling_max_freq_enable:
            file = 'scaling_max_freq'
            on_error = '现将尝试读取`cpuinfo_max_freq`数值，可能对最终结果造成一定的误差，若需获取最准确数据'
        else:
            file = 'cpuinfo_max_freq'
            on_error = '无法继续进行测试'
        f = self.run_shell(f'cat /sys/devices/system/cpu/cpu{idx}/cpufreq/{file}')
        try:
            return int(f)
        except ValueError:
            on_error = f'''文件`{file}`读取遇到错误: {f}\n{on_error}\n
            请尝试关闭手机的开发者模式，重启手机后再尝试重新开启开发者模式并开启USB调试后进行测试.'''
        if file == 'cpuinfo_max_freq':
            raise Exception(on_error)
        self.__cpu_scaling_max_freq_enable = False
        logging.warning(on_error)
        return self.get_cpu_x_max_freq(idx)

    def get_cpu_freq(self) -> float:
        """计算CPU当前频率占比
        :return 当前时刻所有CPU频率之和/所有CPU频率最大值之和
        """
        c = self.get_cpu_count()
        ct = 0
        mt = 0
        for i in range(c):
            ct += self.get_cpu_x_curr_freq(i)
            mt += self.get_cpu_x_max_freq(i)
        return ct * 1.0 / mt

    def get_cpu_global(self) -> SysCPU:
        """
        # 从/proc/stat读取CPU运行信息, 该文件中的所有值都是从系统启动开始累计到当前时刻
        时间数据单位：jiffies。  1jiffies=0.01秒
        # 参考 https://www.cnblogs.com/wangfengju/p/6172440.html
        :return: 返回系统启动以来(总的用户态时间，总的内核态时间)
        """
        #
        # 1: 总的用户态时间
        # 3: 总的内核态时间
        t = re.split(r'\s+', self.run_shell('cat /proc/stat|head -n 1'))
        total = 0
        for x in t[1:8]:
            if not x:
                continue
            total += int(x)
        return SysCPU(int(t[1]), int(t[3]), total, self.get_cpu_freq())

    def get_cpu_details(self, pid: str, for_all=False):
        """
        从/proc/{pid}/stat 读取目标进程的CPU运行信息，该文件的所有值都是从进程创建开始累计到当前时间
        时间数据单位：jiffies。  1jiffies=0.01秒
        # 参考 https://blog.csdn.net/houzhizhen/article/details/79474427
        """
        rs = self.run_shell(f'cat /proc/{pid}/stat')
        if rs.find('No such') != -1:
            # 进程有可能被销毁
            raise KeyError(f'Bad return: {rs}')
        if rs.find('error') != -1:
            raise ValueError(f'Error return: {rs}')
        if for_all:
            return rs
        m = re.split(r'\s+', rs)
        if m:
            return m
        raise ValueError(f'Format error: {rs}')

    def get_process_cpu_usage(self, pid) -> AppCPU:
        """
        获取指定进程CPU占用时间
        :param pid: 进程ID
        :return: (进程用户态所占CPU时间, 系统内核态所占CPU时间)
        """
        logging.debug(f'Getting CPU usage on {pid} ...')
        p = self.get_cpu_details(pid)
        # 13：utime 该进程用户态时间
        # 14：stime 该进程内核态时间
        return AppCPU(int(p[13]), int(p[14]))

    def get_processes_cpu_usage(self, process_id_list: list[int], auto_remove_miss_process=True) -> AppCPU:
        """
        每个App可能会有多个进程
        获取目标Apps进程id列表的最新CPU占用时间汇总
        :param process_id_list: App的进程列表
        :param auto_remove_miss_process: 是否从process_id_list中清理不存在进程ID
        :return: 当前总的目标AppCPU时间
        """
        total_u, total_s = 0, 0
        miss_pid_list = []
        for pi in process_id_list:
            try:
                cpu_use = self.get_process_cpu_usage(pi)
            except KeyError as e:
                if str(e).find('No such') != -1:
                    logging.warning(f'process miss:{pi}')
                    miss_pid_list.append(pi)
                    continue
                raise e
            total_u += cpu_use.user
            total_s += cpu_use.kernel
        if auto_remove_miss_process:
            for xp in miss_pid_list:
                process_id_list.remove(xp)
        return AppCPU(total_s, total_s)

    @staticmethod
    def compute_cpu_rate(
            start_sys_cpu: SysCPU,
            end_sys_cpu: SysCPU,
            start_app_cpu: AppCPU,
            end_app_cpu: AppCPU,
            is_normalized=True
    ) -> (float, float):
        """
        计算一个周期内的App的CPU占用率
        注意：区分规范化和非规范化  https://bbs.perfdog.qq.com/detail-146.html
        :param start_sys_cpu: 周期开始时系统占用CPU时间
        :param end_sys_cpu: 周期结束时系统占用CPU时间
        :param start_app_cpu: 周期开始时应用占用CPU时间
        :param end_app_cpu: 周期结束时应用占用CPU时间
        :param is_normalized: 是否规范化
        :return: (App用户态+内核态占用率，系统总用户态+内核态占用率)
        """
        sys_u = end_sys_cpu.user - start_sys_cpu.user
        sys_s = end_sys_cpu.kernel - start_sys_cpu.kernel
        app_u = end_app_cpu.user - start_app_cpu.user
        app_s = end_app_cpu.kernel - start_app_cpu.kernel
        total_cpu = end_sys_cpu.total - start_sys_cpu.total
        rs = (app_u + app_s) * 1.0 / total_cpu, (sys_u + sys_s) * 1.0 / total_cpu
        if is_normalized:
            rs = rs[0] * end_sys_cpu.freq, rs[1] * end_sys_cpu.freq
            logging.debug('CPU Normalized: %.2f%% on Freq: %.2f%%', rs[0] * 100, end_sys_cpu.freq * 100)
        else:
            logging.debug('CPU: %.2f%%', rs[0] * 100)
        return rs

