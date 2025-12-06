def enqueueFrame(self, frameId, frameData):
    if not frameData or len(frameData) < 100:
        return
    
    with self.queueLock:
        self.frameQueue.append((frameId, frameData))
        self.frameBuffer.append(frameId)

        if len(self.frameQueue) > self.MIN_BUFFER_SIZE:
            self.frameQueue.popleft()

        if len(self.frameBuffer) > self.MAX_BUFFER_SIZE:
            self.frameBuffer.pop(0)

    self.bufferEvent.set()
