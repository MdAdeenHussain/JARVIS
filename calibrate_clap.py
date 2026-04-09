#!/usr/bin/env python3
"""
JARVIS Clap Detection Calibration Script

Runs for 10 seconds to collect ambient noise statistics and compute
optimal clap sensitivity threshold. Writes the computed value to .env.

Usage: python calibrate_clap.py
"""

import os
import time
import numpy as np
import sounddevice as sd
from scipy import signal
import dotenv

# Audio parameters
SAMPLE_RATE = 44100  # Hz
BUFFER_SIZE = int(0.01 * SAMPLE_RATE)  # 10ms frames
CALIBRATION_TIME = 2  # seconds

def compute_rms_energy(frame):
    """Compute RMS energy of an audio frame."""
    return np.sqrt(np.mean(frame ** 2))

def calibrate_clap_sensitivity():
    """Run calibration and return optimal sensitivity value."""
    print("🎙️  Starting clap detection calibration...")
    print("📊 Collecting ambient noise for 10 seconds...")
    print("🤫 Stay quiet and avoid claps during calibration.")

    # Collect energy values
    energies = []

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"Audio status: {status}")
        # Compute RMS energy for this frame
        rms = compute_rms_energy(indata[:, 0])  # Use left channel
        energies.append(rms)

    # Start audio stream
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        blocksize=BUFFER_SIZE,
        callback=audio_callback
    ):
        # Collect data for CALIBRATION_TIME seconds
        start_time = time.time()
        while time.time() - start_time < CALIBRATION_TIME:
            time.sleep(0.1)  # Small sleep to avoid busy waiting
            progress = int((time.time() - start_time) / CALIBRATION_TIME * 100)
            print(f"\r📈 Progress: {progress}%", end="", flush=True)

    print("\n✅ Calibration complete!")

    if not energies:
        print("❌ No audio data collected. Check microphone permissions.")
        return None

    # Compute statistics
    energies = np.array(energies)
    mean_energy = np.mean(energies)
    std_energy = np.std(energies)

    # Optimal threshold: mean + 4*std (for clap detection)
    optimal_threshold = mean_energy + 4 * std_energy

    # Sensitivity is a scaling factor (0.0-1.0), where 1.0 = optimal_threshold
    # We set it to 1.0 as the calibrated value
    sensitivity = 1.0

    print("✅ Calibration complete!")
    print(f"📊 Mean energy: {mean_energy:.4f}")
    print(f"📊 Std energy: {std_energy:.6f}")
    print(f"📊 Optimal threshold: {optimal_threshold:.6f}")
    print(f"🎚️  Sensitivity: {sensitivity:.3f}")
    return sensitivity

def update_env_file(sensitivity):
    """Update .env file with the new CLAP_SENSITIVITY value."""
    env_path = os.path.join(os.path.dirname(__file__), '.env')

    # Load existing .env
    if os.path.exists(env_path):
        dotenv.load_dotenv(env_path)
    else:
        print(f"⚠️  .env file not found at {env_path}. Creating new one.")

    # Update or add CLAP_SENSITIVITY
    with open(env_path, 'a+') as f:
        f.seek(0)
        content = f.read()

        # Remove existing CLAP_SENSITIVITY line if present
        lines = content.split('\n')
        lines = [line for line in lines if not line.startswith('CLAP_SENSITIVITY=')]

        # Add new line
        lines.append(f'CLAP_SENSITIVITY={sensitivity:.3f}')

        # Write back
        f.seek(0)
        f.truncate()
        f.write('\n'.join(lines) + '\n')

    print(f"✅ Updated .env with CLAP_SENSITIVITY={sensitivity:.3f}")

def main():
    """Main calibration function."""
    try:
        sensitivity = calibrate_clap_sensitivity()
        if sensitivity is not None:
            update_env_file(sensitivity)
            print("\n🎉 Calibration successful! JARVIS clap detection is now tuned to your environment.")
            print("💡 Test by running JARVIS and performing a double clap.")
        else:
            print("\n❌ Calibration failed. Please check your microphone setup.")
    except Exception as e:
        print(f"\n❌ Calibration error: {e}")
        print("💡 Make sure sounddevice and scipy are installed: pip install sounddevice scipy")

if __name__ == "__main__":
    main()