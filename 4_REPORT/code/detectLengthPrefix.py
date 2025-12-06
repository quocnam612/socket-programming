def detectLengthPrefix(self):
    pos = self.file.tell()
    peek = self.file.read(5)
    self.file.seek(pos)
    return peek.isdigit()