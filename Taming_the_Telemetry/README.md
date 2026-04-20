## Telemetry-Based Drag and Rolling Resistance Estimation

This script processes vehicle telemetry from a coasting phase to estimate two key parameters:

- Effective drag area \(C_d A\) (aerodynamic drag term)
- Rolling resistance coefficient \(C_{rr}\)

It assumes that during coasting the only longitudinal forces are aerodynamic drag and rolling resistance, and fits a simple deceleration model using least squares.

## Method

For a vehicle of mass \(m\), air density \(\rho\), and speed \(v\), the longitudinal deceleration under coasting is modeled as:

\[
a = -\left(k_1 v^2 + k_2\right)
\]

where:
- \(k_1 = \frac{\rho C_d A}{2 m}\)
- \(k_2 = g C_{rr}\)

From the fitted coefficients \(k_1\) and \(k_2\), we recover:

\[
C_d A = \frac{2 m k_1}{\rho}, \quad C_{rr} = \frac{k_2}{g}
\]

This structure is consistent with the drag and rolling terms in the master power-balance model used elsewhere in the project. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/5504f262-3dd6-4353-9ef0-11f66bf1e996/strategy_report.txt)

## Data Requirements

The script expects a CSV file `telemetry_A.csv` with at least:

- `timestamp`: ISO datetime string
- `velocity_ms`: vehicle speed in m/s
- `Gradient_deg`: road gradient in degrees (used to remove non-flat segments)

The file is loaded and pre-processed with Pandas. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/f4219e90-c3ae-4c68-be67-7d394240510c/visualizer.py)

## Processing Pipeline

1. **Load and timestamp parsing**

   ```python
   df = pd.read_csv('telemetry_A.csv')
   df['timestamp'] = pd.to_datetime(df['timestamp'])
   ```

2. **Basic cleaning**

   - Remove zero or negative velocities.
   - Drop rows with missing values.

   ```python
   df = df[df['velocity_ms'] > 0]
   df = df.dropna()
   ```

3. **Outlier handling**

   - Remove segments with \(|\text{Gradient\_deg}| \ge 2\) to focus on near-flat coasting.  
   - Remove velocity outliers using the interquartile range (IQR) rule.

   ```python
   df = df[np.abs(df['Gradient_deg']) < 2]

   q1 = df['velocity_ms'].quantile(0.25)
   q3 = df['velocity_ms'].quantile(0.75)
   iqr = q3 - q1
   df = df[(df['velocity_ms'] > q1 - 1.5 * iqr) &
           (df['velocity_ms'] < q3 + 1.5 * iqr)]
   ```

4. **Smoothing**

   - Apply a centered rolling mean (window 10 samples) to velocity, then drop edge NaNs.

   ```python
   df['velocity_ms'] = df['velocity_ms'].rolling(10, center=True).mean()
   df = df.dropna()
   ```

5. **Compute time and acceleration**

   - Convert timestamps to seconds.
   - Compute \(dt\) and \(dv\), filter for positive time steps.
   - Compute acceleration \(a = dv/dt\) at each sample.

   ```python
   t = df['timestamp'].astype('int64') / 1e9
   v = df['velocity_ms'].values

   dt = np.diff(t)
   dv = np.diff(v)

   mask = dt > 0
   dt = dt[mask]
   dv = dv[mask]
   v = v[:-1][mask]

   a = dv / dt
   ```

6. **Select physically meaningful data**

   - Keep only deceleration points (\(a < 0\)), since coasting is speed decay.
   - Remove acceleration outliers using a \(2\sigma\) rule on \(a\).

   ```python
   mask_phys = a < 0
   a = a[mask_phys]
   v = v[mask_phys]

   a_mean = np.mean(a)
   a_std = np.std(a)
   mask_a = np.abs(a - a_mean) < 2 * a_std
   a = a[mask_a]
   v = v[mask_a]
   ```

7. **Linear regression**

   - Fit \(-a = k_1 v^2 + k_2\) via least squares.

   ```python
   X = np.column_stack([v**2, np.ones_like(v)])
   y = -a
   coeffs, _, _, _ = lstsq(X, y, rcond=None)
   k1, k2 = coeffs
   ```

8. **Parameter extraction**

   - Use nominal values for air density, mass, and gravity:

     ```python
     rho = 1.225  # kg/m³
     m = 300      # kg
     g = 9.81     # m/s²
     ```

   - Compute \(C_dA\) and \(C_{rr}\):

     ```python
     CdA = (2 * m * k1) / rho
     Crr = k2 / g

     print(f"CdA: {CdA:.4f} m²")
     print(f"Crr: {Crr:.4f}")
     ```

9. **Sanity checks**

   Simple sign checks to catch obviously non-physical results:

   ```python
   if k1 < 0:
       print("⚠️ Warning: Negative CdA detected — check filtering.")
   if k2 < 0:
       print("⚠️ Warning: Negative Crr detected — possible noise influence.")
   ```

   Negative \(k_1\) or \(k_2\) can indicate insufficiently filtered data, gradient bias, or measurement noise.

10. **Visualization**

    - Compare measured deceleration to the fitted curve.

    ```python
    a_pred = -(k1 * v**2 + k2)

    plt.scatter(v, a, s=10, label="Actual")
    plt.plot(v, a_pred, color='red', label="Fitted")
    plt.xlabel("Velocity (m/s)")
    plt.ylabel("Acceleration (m/s²)")
    plt.title("Coasting Curve Fit (Filtered Data)")
    plt.legend()
    plt.show()
    ```

    The script then repeats the plot without the “Filtered Data” wording.

## Assumptions and Limitations

- Coasting sections are approximately flat (small gradient), with no power applied.
- Wind effects, drivetrain losses, and bearing drag are lumped into \(C_{rr}\).
- A single constant air density and vehicle mass are used.
- Telemetry must have sufficiently high resolution and low noise for the fitted parameters to be meaningful. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/5504f262-3dd6-4353-9ef0-11f66bf1e996/strategy_report.txt)

## How to Run

1. Place `telemetry_A.csv` in the working directory with the required columns.
2. Install dependencies:

   ```bash
   pip install numpy pandas matplotlib
   ```

3. Run:

   ```bash
   python telemetry_fit.py
   ```

You’ll see printed estimates for \(C_dA\) and \(C_{rr}\), followed by plots showing how well the model fits the measured coasting deceleration.

