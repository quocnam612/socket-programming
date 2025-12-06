class VideoStream:
	def __init__(self, filename):
		self.filename = filename
		try:
			self.file = open(filename, 'rb')
		except:
			raise IOError
		self.frameNum = 0
		self.lengthPrefixed = self.detectLengthPrefix()

	def nextFrame(self):
		if self.lengthPrefixed:
			data = self.file.read(5)
			if data:
				frameLength = int(data)
				data = self.file.read(frameLength)
				self.frameNum += 1
			return data
		return self._readRawFrame()

	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum

	def detectLengthPrefix(self):
		pos = self.file.tell()
		peek = self.file.read(5)
		self.file.seek(pos)
		return peek.isdigit()

	def _readRawFrame(self):
		prev = self.file.read(1)
		if not prev:
			return b''

		while True:
			curr = self.file.read(1)
			if not curr:
				return b''
			if prev == b'\xff' and curr == b'\xd8':
				frame = bytearray(prev + curr)
				break
			prev = curr

		while True:
			curr = self.file.read(1)
			if not curr:
				break
			frame += curr
			if len(frame) >= 2 and frame[-2:] == b'\xff\xd9':
				self.frameNum += 1
				return bytes(frame)

		if frame:
			self.frameNum += 1
			return bytes(frame)
		return b''
