#!/usr/bin/env python3
"""Train CNN for MGC.F and export to ONNX"""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.preprocessing import MinMaxScaler
import json

# Load MGC.F data
print("Loading MGC.F data...")
df = pd.read_csv('/home/node/.openclaw/workspace/MGC.F.csv')
df.columns = [c.lower() for c in df.columns]
df['datetime'] = pd.to_datetime(df['datetime'])
df.set_index('datetime', inplace=True)
df = df.dropna(subset=['close'])
df = df.sort_index()

closes = df['close'].values.reshape(-1, 1)
print(f"Data shape: {closes.shape}")

scaler = MinMaxScaler(feature_range=(0, 1))
scaled = scaler.fit_transform(closes).flatten()

seq_len = 20
X, y = [], []
for i in range(seq_len, len(scaled)):
    X.append(scaled[i-seq_len:i])
    y.append(scaled[i])
X, y = np.array(X), np.array(y)
X = X.reshape(-1, seq_len, 1)  # (samples, seq_len, channels)
print(f"Sequences: X={X.shape}, y={y.shape}")

train_size = int(len(X) * 0.9)
xt, yt = X[:train_size], y[:train_size]
print(f"Training size: {train_size}")

# Build MLP model (simple Dense layers - no conv/pool)
model = tf.keras.Sequential([
    tf.keras.layers.Flatten(input_shape=[seq_len, 1]),
    tf.keras.layers.Dense(64, activation='relu'),
    tf.keras.layers.Dense(32, activation='relu'),
    tf.keras.layers.Dense(16, activation='relu'),
    tf.keras.layers.Dense(1)
])
model.compile(optimizer=tf.keras.optimizers.Adam(0.01), loss='mse')

print("Training CNN...")
model.fit(xt, yt, epochs=5, batch_size=4, verbose=0)
print("Training complete!")

# Test prediction
test_pred = model.predict(X[train_size:train_size+1], verbose=0)
print(f"Test prediction: {test_pred[0][0]:.4f}")

# Export to ONNX
import tf2onnx
output_path = '/home/node/.openclaw/workspace/MGC_cnn.onnx'

# Create model with named input/output
inp = tf.keras.Input(shape=[seq_len, 1], name='input')
out = model(inp, training=False)
named_model = tf.keras.Model(inp, out)

import onnx
onnx_model = tf2onnx.convert.from_keras(named_model, opset=13)
if isinstance(onnx_model, tuple):
    onnx.save(onnx_model[0], output_path)
else:
    onnx.save(onnx_model, output_path)

if os.path.exists(output_path):
    size = os.path.getsize(output_path) / 1024
    print(f"✅ ONNX model saved: {output_path} ({size:.1f} KB)")
else:
    print("❌ ONNX export failed")

# Save scaler params
scaler_params = {
    'min': float(scaler.data_min_[0]),
    'max': float(scaler.data_max_[0]),
    'seq_len': seq_len
}
with open('/home/node/.openclaw/workspace/MGC_scaler.json', 'w') as f:
    json.dump(scaler_params, f)
print(f"Scaler saved: MGC_scaler.json")

print("\nDone!")