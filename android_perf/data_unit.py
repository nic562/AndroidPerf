
class DataUnit:
    def __init__(self, name: str, flag: str):
        self.name = name
        self.flag = flag

    def __str__(self):
        return self.name

    def byte_exchange(self, value: (int, float)) -> float:
        """
        将 byte 转换为当前单位
        :param value: 单位为byte的数据
        :return:
        """
        if self.name == KB.name:
            f = 1
        elif self.name == MB.name:
            f = 2
        elif self.name == GB.name:
            f = 3
        else:
            f = 0
        return round(value / (1024 ** f), 2)


BYTE = DataUnit('Byte', 'b')
KB = DataUnit('KB', 'k')
MB = DataUnit('MB', 'm')
GB = DataUnit('GB', 'g')

