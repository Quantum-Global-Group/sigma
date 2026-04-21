"""
PyTorch LSTM signal classifier.

Architecture:
  Input  → 2-layer LSTM (hidden=64) → Dropout → Linear → Softmax (3 classes)

Trained with cross-entropy loss on sliding windows of feature vectors.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ml.inference import SignalResult
from ml.models.base import BaseSignalModel, label_to_signal

logger = logging.getLogger(__name__)

SEQ_LEN = 20
HIDDEN = 64
N_CLASSES = 3


def _torch():
    """Lazy torch import — avoids loading ~500MB at startup if LSTM isn't used."""
    import torch  # type: ignore
    import torch.nn as nn  # type: ignore
    return torch, nn


class LSTMModel:
    """Internal nn.Module factory — instantiated lazily so `import torch` is deferred."""

    @staticmethod
    def build(n_features: int):
        torch, nn = _torch()

        class _Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.lstm = nn.LSTM(input_size=n_features, hidden_size=HIDDEN, num_layers=2, batch_first=True, dropout=0.2)
                self.head = nn.Sequential(
                    nn.Linear(HIDDEN, 32),
                    nn.ReLU(),
                    nn.Dropout(0.2),
                    nn.Linear(32, N_CLASSES),
                )

            def forward(self, x):
                out, _ = self.lstm(x)
                return self.head(out[:, -1, :])

        return _Net()


class LSTMSignalModel(BaseSignalModel):
    model_version = "lstm_v1.0"

    def __init__(self, n_features: int | None = None):
        self.n_features = n_features
        self.feature_names: list[str] = []
        self.net = None
        self._fitted = False

    def _make_sequences(self, X: np.ndarray, y: np.ndarray | None = None):
        """Build sliding windows of length SEQ_LEN. Drops the first SEQ_LEN-1 rows."""
        n = X.shape[0]
        if n <= SEQ_LEN:
            return np.zeros((0, SEQ_LEN, X.shape[1])), (np.zeros((0,), dtype=int) if y is not None else None)

        seqs = np.stack([X[i - SEQ_LEN + 1 : i + 1] for i in range(SEQ_LEN - 1, n)])
        if y is not None:
            return seqs, y[SEQ_LEN - 1:]
        return seqs, None

    def train(self, X: pd.DataFrame, y: np.ndarray, epochs: int = 30, batch_size: int = 32, lr: float = 1e-3) -> None:
        torch, nn = _torch()

        self.feature_names = list(X.columns)
        self.n_features = X.shape[1]
        self.net = LSTMModel.build(self.n_features)

        X_seq, y_seq = self._make_sequences(X.values, y)
        if X_seq.shape[0] == 0:
            raise ValueError(f"Need at least {SEQ_LEN + 1} samples for LSTM training")

        X_tensor = torch.tensor(X_seq, dtype=torch.float32)
        y_tensor = torch.tensor(y_seq, dtype=torch.long)

        optimizer = torch.optim.Adam(self.net.parameters(), lr=lr)
        loss_fn = nn.CrossEntropyLoss()

        self.net.train()
        for epoch in range(epochs):
            perm = torch.randperm(X_tensor.shape[0])
            losses = []
            for i in range(0, X_tensor.shape[0], batch_size):
                idx = perm[i : i + batch_size]
                xb, yb = X_tensor[idx], y_tensor[idx]
                optimizer.zero_grad()
                logits = self.net(xb)
                loss = loss_fn(logits, yb)
                loss.backward()
                optimizer.step()
                losses.append(float(loss))
            if (epoch + 1) % 5 == 0:
                logger.info("LSTM epoch %d/%d loss=%.4f", epoch + 1, epochs, np.mean(losses))

        self._fitted = True

    def predict(self, features: pd.DataFrame) -> SignalResult:
        if not self._fitted or features.empty or self.net is None:
            return SignalResult("HOLD", 0.5, 0.0)

        torch, _ = _torch()
        if self.feature_names:
            X = features[self.feature_names].values
        else:
            X = features.values

        if X.shape[0] < SEQ_LEN:
            return SignalResult("HOLD", 0.5, 0.0)

        seq = X[-SEQ_LEN:][None, :, :]
        with torch.no_grad():
            self.net.eval()
            logits = self.net(torch.tensor(seq, dtype=torch.float32))
            proba = torch.softmax(logits, dim=-1).numpy()[0]

        label = int(np.argmax(proba))
        confidence = float(proba[label])
        predicted_return = float((proba[2] - proba[0]) * 0.05)

        result = SignalResult(label_to_signal(label), round(confidence, 4), round(predicted_return, 6))
        result.model_version = self.model_version
        return result

    def save(self, path: str) -> None:
        torch, _ = _torch()
        torch.save({
            "state_dict": self.net.state_dict(),
            "n_features": self.n_features,
            "feature_names": self.feature_names,
            "model_version": self.model_version,
        }, path)

    @classmethod
    def load(cls, path: str) -> "LSTMSignalModel":
        torch, _ = _torch()
        data = torch.load(path, map_location="cpu", weights_only=False)
        instance = cls(n_features=data["n_features"])
        instance.feature_names = data["feature_names"]
        instance.net = LSTMModel.build(data["n_features"])
        instance.net.load_state_dict(data["state_dict"])
        instance.model_version = data.get("model_version", "lstm_v1.0")
        instance._fitted = True
        return instance
