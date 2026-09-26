// Browsers only allow audio after a user gesture; unlock on the first click on the page.
let context: AudioContext | null = null;

export function unlockSound() {
  try {
    context ??= new AudioContext();
    void context.resume();
  } catch {
    context = null;
  }
}

/** Two short notes. Plays in background tabs once unlocked. */
export function chime() {
  if (!context) return;
  try {
    const start = context.currentTime;
    [880, 1318.5].forEach((frequency, index) => {
      const oscillator = context!.createOscillator();
      const gain = context!.createGain();
      const at = start + index * 0.14;
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.18, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.35);
      oscillator.connect(gain);
      gain.connect(context!.destination);
      oscillator.start(at);
      oscillator.stop(at + 0.4);
    });
  } catch {
    // Sound is a courtesy; the page still shows every notice.
  }
}
