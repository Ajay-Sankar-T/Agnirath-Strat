## PID class review

Your PID structure has the standard proportional, integral, and derivative terms, and your output clamping is a reasonable first anti-windup step. [mathworks](https://www.mathworks.com/help/simulink/slref/anti-windup-control-using-a-pid-controller.html)
However, the derivative is not actually filtered despite the comment saying “filtered”; it is just a raw discrete derivative, which can be noisy in real systems. [scilab](https://www.scilab.org/pid-anti-windup-schemes)
Also, your anti-windup method simply undoes the current integration step when the output saturates, which is acceptable as a basic conditional-integration approach, but more robust schemes often use back-calculation. [cds.caltech](https://www.cds.caltech.edu/~murray/courses/cds101/fa02/caltech/astrom-ch6.pdf)

## CartPole logic

For `CartPole-v1`, the observation has four values and the pole angle is indeed at index `2`, so using `obs [gymnasium.farama](https://gymnasium.farama.org/v1.1.0/introduction/record_agent/)` as the control error target is correct. [gymnasium.farama](https://gymnasium.farama.org/environments/classic_control/cart_pole/)
The action space is discrete with two actions, where `0` pushes left and `1` pushes right, so converting a continuous PID signal into a binary action by thresholding is a sensible simplification. [gymnasium.farama](https://gymnasium.farama.org/introduction/basic_usage/)
That said, using only pole angle usually works poorly compared with using both angle and angular velocity, because CartPole is a dynamic balancing problem rather than a pure setpoint regulation problem. [gymnasium.farama](https://gymnasium.farama.org/environments/classic_control/cart_pole/)

## Why it may perform badly

A plain PID tuned only on pole angle often ends episodes quickly because CartPole also depends strongly on angular velocity and cart motion. [gymnasium.farama](https://gymnasium.farama.org/environments/classic_control/cart_pole/)
Your integral term is usually not very helpful for CartPole and can even hurt stability, so many hand-built controllers use mostly proportional-derivative behavior instead. [gymnasium.farama](https://gymnasium.farama.org/environments/classic_control/cart_pole/)
In addition, the sign convention for `action = 1 if control > 0 else 0` may need to be flipped depending on how you define the error, since action `0` is left and `1` is right. [gymnasium.farama](https://gymnasium.farama.org/environments/classic_control/cart_pole/)

## Cleaned-up version

Here is a cleaner script version for normal Python use:

```python
import os
import numpy as np
import matplotlib.pyplot as plt
import gymnasium as gym
from gymnasium.wrappers import RecordVideo


class PIDController:
    def __init__(self, Kp, Ki, Kd, setpoint=0.0, dt=0.1, output_limits=(None, None)):
        self.Kp, self.Ki, self.Kd = Kp, Ki, Kd
        self.setpoint = setpoint
        self.dt = dt
        self.output_limits = output_limits
        self._integral = 0.0
        self._prev_error = 0.0

    def update(self, measured_value):
        error = self.setpoint - measured_value

        P = self.Kp * error

        self._integral += error * self.dt
        I = self.Ki * self._integral

        D = self.Kd * (error - self._prev_error) / self.dt
        self._prev_error = error

        raw_output = P + I + D
        output = raw_output

        low, high = self.output_limits
        if low is not None:
            output = max(low, output)
        if high is not None:
            output = min(high, output)

        if output != raw_output:
            self._integral -= error * self.dt

        return output


# -----------------------------
# 1) Velocity-control example
# -----------------------------
pid = PIDController(Kp=0.3, Ki=0.03, Kd=0.02, setpoint=50, dt=0.1, output_limits=(0, 1000))

measured_velocity = 45
motor_power = pid.update(measured_velocity)
print(f"Motor Power Command: {motor_power:.1f} W")

time = np.arange(0, 20, 0.1)
target_velocity = 50
measured_velocity = np.zeros_like(time)
measured_velocity[0] = 40

pid = PIDController(Kp=0.3, Ki=0.03, Kd=0.02, setpoint=target_velocity, dt=0.1, output_limits=(0, 1000))
motor_powers = []

for i in range(1, len(time)):
    u = pid.update(measured_velocity[i - 1])
    motor_powers.append(u)
    measured_velocity[i] = measured_velocity[i - 1] + (u / 1000) * 0.1

plt.figure(figsize=(12, 6))
plt.subplot(2, 1, 1)
plt.plot(time, measured_velocity, label="Measured Velocity")
plt.axhline(target_velocity, color="red", linestyle="--", label="Target Velocity")
plt.xlabel("Time (s)")
plt.ylabel("Velocity (km/h)")
plt.legend()
plt.grid(True)

plt.subplot(2, 1, 2)
plt.plot(time[1:], motor_powers, label="Motor Power Command", color="orange")
plt.xlabel("Time (s)")
plt.ylabel("Motor Power (W)")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()


# -----------------------------
# 2) CartPole with PID
# -----------------------------
video_dir = "./videos"
os.makedirs(video_dir, exist_ok=True)

env = gym.make("CartPole-v1", render_mode="rgb_array")
env = RecordVideo(env, video_folder=video_dir, episode_trigger=lambda ep: True)

obs, info = env.reset()

Kp = 70
Ki = 0.0
Kd = 15

integral = 0.0
prev_error = 0.0
dt = 0.02

for step in range(1000):
    angle = obs [gymnasium.farama](https://gymnasium.farama.org/v1.1.0/introduction/record_agent/)
    angle_rate = obs [scilab](https://www.scilab.org/pid-anti-windup-schemes)

    error = angle
    integral += error * dt
    integral = np.clip(integral, -1.0, 1.0)
    derivative = (error - prev_error) / dt

    control = Kp * error + Ki * integral + Kd * derivative

    action = 1 if control > 0 else 0

    obs, reward, terminated, truncated, info = env.step(action)
    prev_error = error

    if terminated or truncated:
        print(f"Episode ended at step {step}")
        break

env.close()
```

## Practical fixes

- Put installation in the terminal, not inside the script: `pip install "gymnasium[classic-control]"`. [gymnasium.farama](https://gymnasium.farama.org/v1.1.0/introduction/record_agent/)
- Import `numpy` before any use of `np`. [ppl-ai-file-upload.s3.us-east-1.amazonaws](https://ppl-ai-file-upload.s3.us-east-1.amazonaws.com/web/direct-files/attachments/128877345/f4219e90-c3ae-4c68-be67-7d394240510c/visualizer.py?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Checksum-Mode=ENABLED&X-Amz-Credential=ASIA2F3EMEYE5M64JHG4%2F20260420%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20260420T182337Z&X-Amz-Expires=3600&X-Amz-Security-Token=IQoJb3JpZ2luX2VjEFoaCXVzLWVhc3QtMSJGMEQCIH%2ByXhvA5AyYSLmVvY7Vk65g4Z42FFQ1CAv4LZuO5jT8AiAladruoWz4KcDrKQ6JPtmiASnwLDJ%2F0QEq4WguDkji%2BirrBAgjEAEaDDY5OTc1MzMwOTcwNSIM6H2IQdmkw8GbDtW3KsgEwWlCy2jUh3INODNl4We2H4NtflV4ah3kN%2FzEUP%2Fa08wv4VoE365ImgK1V5DW67uh8OtTveEXK8FWDz2N4Yyvs2P1h8Tgfy7tTqYJb%2FOaDnGu0E8PnInzQudeDbmfjS8pzPsH1Cvc0P524yqGohl8BWYm0xqBPYr42THAikfW0fGAM%2Bv75L%2BPlrxxzMzqiGMJzI3r5gW%2FVvVbbJ4VYN84u27nnbmamF0yGz6LHp3IwRnrAR%2FCrwAqvr8269hGak98QItzHHuWVnO7sSWU%2FZ09ztl7y5i%2BxWMCR6xskW0yxXYUQ3b1pJs0Vs7F0ZDP1%2FXvz1urWscg8cLiQXb1KkJbyGVTdYXdzBsPo9idbbMBcI1N2yoqoddYESvqnRd22lV%2BC%2BKWzB2j7BwVEwVCpfwMk77iR4LAWZ45QFcqmVuhjeMPV4ntaCBT02wcTQxWPJOZ3AV7q6Yvm3fiisyc0WDla%2B8I9se5xVRYWVnSL7xxQTLQggXrcADjSTfsZrXuqjb7aysu3AbkyLbr4LaCn1T2sBIRurX4dcrtYXSvhCxXA0pVdYc1q0KAdOAiwDs3XLxR2GhlPFjCbI26eM1GYIqNSqtx4kx3QekJQt7XCtZ7XE9l%2BUxAD7bVZzBocgxT3DhYytiWfbdQgrBjxjW32MpTT%2BC8%2BxMg4pRQS2aGy6aQYaFpWwb%2Bro03ltecNZA79MCbs1sEfeKEYYJE2d3UPZlk1rxz2mZmpPxa1s5q45uxVWzB2Z%2FOoHaIx0VZyOKNW7dp%2FSdbKCCk1%2BcwtMmZzwY6mQEFAgtc11sMD8VBDJXpIrEBDDk0JwfmP17argJG9VOXBlnHhk0vPu4Kp4E%2BUDisMNGeTHJb6NWLHI3ide1yl5Yem6I0AQ6%2BqkV3OTlJBk98OVJUUj9lShJNlmTXikq30rPwiJoiYBQPUfjlaguzKD93sWBowcQLKBIyS4%2FbUiwG8YQXUkHqV4ZmIsdQjkLQj93EGAbPt7Y8RkE%3D&X-Amz-SignedHeaders=host&x-id=GetObject&X-Amz-Signature=7e4887e395c3bd88308a01ef3f093ab17f2fd36425aa08f10388404c6a673dac)
- Keep only one CartPole block, not three versions. [gymnasium.farama](https://gymnasium.farama.org/environments/classic_control/cart_pole/)
- Use `rgb_array` when recording video with `RecordVideo`. [gymnasium.farama](https://gymnasium.farama.org/v0.29.0/_modules/gymnasium/experimental/wrappers/rendering/)
- Start with `Ki = 0` for CartPole and tune `Kp` and `Kd` first. [scilab](https://www.scilab.org/pid-anti-windup-schemes)

## Better control idea

A stronger heuristic controller for CartPole usually uses both angle and angular velocity, for example a linear rule like  
\(u \propto k_1 \theta + k_2 \dot{\theta} + k_3 x + k_4 \dot{x}\), which fits the environment dynamics better than pure angle PID. [gymnasium.farama](https://gymnasium.farama.org/environments/classic_control/cart_pole/)
If your goal is course learning, PID is a nice experiment; if your goal is to keep the pole balanced for long episodes, state-feedback or reinforcement learning is usually a better fit. [github](https://github.com/microsoft/ML-For-Beginners/blob/main/8-Reinforcement/2-Gym/README.md)
