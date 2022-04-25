
class DataUnit:
    def __init__(self, name: str, flag: str):
        self.name = name
        self.flag = flag

    def __str__(self):
        return self.name

    def format(self, value: (int, float)) -> float:
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

