from kivy.app import App
from kivy.uix.label import Label
import sounddevice as sd
import numpy as np
from tuner import detectar_frequencia, encontrar_nota

fs = 44100

class TunerApp(App):
    def build(self):
        self.label = Label(text="Toque uma corda...",
                           font_size='20sp')
        self.start_listening()
        return self.label

    def start_listening(self):
        def callback(indata, frames, time, status):
            audio = indata[:, 0]
            freq = detectar_frequencia(audio)

            if freq > 0:
                nota = encontrar_nota(freq)
                self.label.text = f"{nota} - {freq:.2f} Hz"

        self.stream = sd.InputStream(callback=callback,
                                     channels=1,
                                     samplerate=fs)
        self.stream.start()

TunerApp().run()
