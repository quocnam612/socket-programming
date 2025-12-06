def updateStats(self):
    now = time.time()
    elapsed = now - self.startTime if self.startTime else 0
    fps = len(self.frameTimes)
    throughput = (self.bytesReceived * 8 / 1000) / elapsed if elapsed > 0 else 0
    stats = (
        f"Frame: {self.frameNbr} "
        f"| Packets: {self.packetCount} "
        f"| Loss(frames): {self.frameLoss} "
        f"| FPS: {fps:.2f} "
        f"| Net: {throughput:.2f} kbps"
    )
    self.statLabel.configure(text=stats)
    self.frameTimes.clear()
