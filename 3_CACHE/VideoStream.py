class VideoStream:
	def __init__(self, filename):
		self.filename = filename
		try:
			self.file = open(filename, 'rb')
		except:
			raise IOError
		self.frameNum = 0
		self.totalFrames = None
		
	def nextFrame(self):
		"""Get next frame."""
		data = self.file.read(5) # Get the framelength from the first 5 bits
		if data: 
			framelength = int(data)
							
			# Read the current frame
			data = self.file.read(framelength)
			self.frameNum += 1
		return data
		
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum
	
	def getTotalFrames(self):
        #Đọc file 1 lần để biết tổng frame"""
		if self.totalFrames is not None:
			return self.totalFrames

		current_pos = self.file.tell()  # lưu vị trí hiện tại
		self.file.seek(0)  # quay về đầu file
		count = 0
		while True:
			length_bytes = self.file.read(5)
			if not length_bytes:
				break
			length = int(length_bytes.decode())
			self.file.seek(length, 1)  # nhảy qua frame
			count += 1
		self.totalFrames = count
		self.file.seek(current_pos)  # quay lại vị trí cũ
		return self.totalFrames
	