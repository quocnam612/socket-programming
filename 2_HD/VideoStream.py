class VideoStream:
	SOI = b'\xff\xd8'  # JPEG start of image
	EOI = b'\xff\xd9'  # JPEG end of image
	CHUNK_SIZE = 4096

	def __init__(self, filename): # Constructor
		self.filename = filename
		try:
			self.file = open(filename, 'rb') # read binary from file
		except:
			raise IOError # throw Input/Output error
		self.frameNum = 0
		self.buffer = bytearray()
		self.eof = False
		
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
	
	
