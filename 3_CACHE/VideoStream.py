class VideoStream:
    SOI = b'\xff\xd8'  # JPEG start of image
    EOI = b'\xff\xd9'  # JPEG end of image
    CHUNK_SIZE = 4096

    def __init__(self, filename):  # Constructor
        self.filename = filename
        try:
            self.file = open(filename, 'rb')  # read binary from file
        except:
            raise IOError  # throw Input/Output error
        self.frameNum = 0
        self.buffer = bytearray()
        self.eof = False
        self.totalFrames = None

    def nextFrame(self):
        """Extract next JPEG frame by scanning for SOI/EOI markers."""
        if self.eof and not self.buffer:
            return b''

        while True:
            start = self._find_marker(self.SOI)
            if start == -1:
                if not self._fillBuffer():
                    self.buffer.clear()
                    return b''
                continue

            end = self._find_marker(self.EOI, start + 2)
            if end == -1:
                if not self._fillBuffer():
                    self.buffer.clear()
                    return b''
                continue

            frame = bytes(self.buffer[start:end + 2])
            del self.buffer[:end + 2]
            self.frameNum += 1
            return frame

    def frameNbr(self):
        """Get frame number."""
        return self.frameNum

    def getTotalFrames(self):

        # 1. Kiểm tra lại self.totalFrames
        if self.totalFrames is not None and self.totalFrames > 0:
            # Nếu đã tính toán và kết quả lớn hơn 0, trả về ngay
            return self.totalFrames

        currentPos = self.file.tell()
        self.file.seek(0, 0)  # Quay về đầu file để đếm
        self.buffer.clear()  # Xóa buffer hiện tại
        self.eof = False  # Reset cờ EOF
        count = 0

        while True:
            start = self._find_marker(self.SOI)
            if start == -1:
                # Không tìm thấy SOI. Đọc thêm dữ liệu (nếu còn)
                if not self._fillBuffer():
                    break  # Hết file
                continue

            # Tìm EOI từ sau SOI
            end = self._find_marker(self.EOI, start + len(self.SOI))
            if end == -1:
                # Không tìm thấy EOI. Đọc thêm dữ liệu (nếu còn)
                if not self._fillBuffer():
                    # Nếu hết file mà vẫn không tìm thấy EOI, bỏ qua phần rác
                    break
                continue

            # Tìm thấy một khung hình
            count += 1

            # Xóa khung hình đã đếm khỏi buffer (bao gồm EOI 2 bytes)
            del self.buffer[:end + len(self.EOI)]

        self.totalFrames = count
        self.file.seek(currentPos)  # Quay về vị trí ban đầu
        self.buffer.clear()  # Dọn dẹp buffer sau khi đếm
        self.eof = False
        return self.totalFrames


    def _find_marker(self, marker, start=0):
        try:
            return self.buffer.index(marker, start)
        except ValueError:
            return -1

    def _fillBuffer(self):
        chunk = self.file.read(self.CHUNK_SIZE)
        if not chunk:
            self.eof = True
            return False
        self.buffer.extend(chunk)
        return True


