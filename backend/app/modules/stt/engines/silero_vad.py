import numpy as np


class SileroVAD:
    def __init__(self, fake=False):
        self.fake = fake
        self.pending = np.empty(0, dtype=np.float32)
        self.position = 0
        self.last_speech = 0
        self.detected = False
        self.speech_ranges = []
        if not fake:
            from silero_vad import load_silero_vad

            self.model = load_silero_vad(onnx=True)

    def feed(self, audio):
        self.pending = np.concatenate((self.pending, audio))
        while len(self.pending) >= 512:
            chunk, self.pending = self.pending[:512], self.pending[512:]
            if self.fake:
                speech = np.max(np.abs(chunk)) > 0.01
            else:
                import torch

                speech = float(self.model(torch.from_numpy(chunk.copy()), 16000)) >= 0.5
            self.position += 512
            if speech:
                self.last_speech = self.position
                self.detected = True
                if self.speech_ranges and self.position - 512 - self.speech_ranges[-1][1] <= 11200:
                    self.speech_ranges[-1][1] = self.position
                else:
                    self.speech_ranges.append([self.position - 512, self.position])
        return self.last_speech
