def playbackLoop(self):
    nextFrameDeadline = time.time()
    while not self.displayEvent.is_set():
        frame = None
        with self.queueLock:
            if self.frameQueue:
                frame = self.frameQueue.popleft()
        if frame:
            frameId, frameData = frame
            self.frameNbr = frameId
            self.framesDisplayed += 1
            self.playedFrames += 1
            self.updateMovie(frameData)
            self.updateStatsLabel()
            nextFrameDeadline = max(time.time(), nextFrameDeadline)
            sleepTime = max(0, nextFrameDeadline - time.time())
        else:
            self.bufferEvent.wait(TARGET_FRAME_INTERVAL)
            self.bufferEvent.clear()
            sleepTime = TARGET_FRAME_INTERVAL
        time.sleep(sleepTime)
        nextFrameDeadline = time.time() + TARGET_FRAME_INTERVAL
