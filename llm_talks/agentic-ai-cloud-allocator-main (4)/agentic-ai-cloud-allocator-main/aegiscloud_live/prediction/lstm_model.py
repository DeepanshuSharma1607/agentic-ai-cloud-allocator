"""
lstm_model.py - the exact LSTM from your notebook (MultiFeatureLSTMForecaster).

Layer names (`lstm`, `head`) must not change, otherwise the saved weights in the .pt file will not load.
Input : seq    (batch, W, n_features)  the last W rows of the 8 metrics, log1p + standardised
        static (batch, n_static)       4 numbers: yesterday-at-target, yesterday change, sin, cos
Output: (batch,) the standardised change in log(requests) between now and now + H
"""
import torch
import torch.nn as nn


class MultiFeatureLSTMForecaster(nn.Module):
    def __init__(self, n_features, n_static, hidden=64):
        super().__init__()
        self.lstm = nn.LSTM(input_size=n_features, hidden_size=hidden, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden + n_static, 64), nn.ReLU(), nn.Linear(64, 1))

    def forward(self, seq, static):
        _, (h, _) = self.lstm(seq)
        return self.head(torch.cat([h[-1], static], dim=1)).squeeze(1)
