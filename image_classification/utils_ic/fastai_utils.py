# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from time import time
from typing import Any, List

from IPython.display import display

from fastai.basic_train import LearnerCallback
from fastai.core import PBar
from fastai.torch_core import TensorOrNumList
from fastprogress.fastprogress import format_time

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

import torch
from torch import Tensor


class TrainMetricsRecorder(LearnerCallback):
    _order = -20  # Needs to run before the recorder

    def __init__(self, learn, n_batch: int = None, show_graph: bool = False, silent: bool = False):
        """Fastai Train hook to evaluate metrics on train and validation set for every epoch.

        This class works with the metrics functions whose signature is fn(input:Tensor, targs:Tensor),
        e.g. fastai.metrics.accuracy and error_rate.
        For custom metrics, see https://docs.fast.ai/metrics.html#Creating-your-own-metric

        Note, Learner's Recorder callback tracks the metrics and loss on the validation set and
        ShowGraph callback plots the loss on train and validation sets while training.
        TrainMetricsRecorder, on the other hand, records the metrics on the training set and plot them as well.

        Arguments:
            learn (Learner): Fastai Learner object
            n_batch (int): Number of train batches to use when evaluate metrics on the training set.
                If None, use all the training set which will take longer time.
            show_graph (bool): If True, draw metrics after each epoch.
            silent (bool): If True, does not show the result table and graphs.

        Examples:
            >>> learn = cnn_learner(data, model, metrics=[accuracy])
            >>> train_metrics_cb = TrainMetricsRecorder(n_batch=1)
            >>> learn.callbacks.append(train_metrics_cb)
            >>> learn.fit(epochs=10, lr=0.001)
            >>> train_metrics_cb.plot()

            or

            >>> learn = cnn_learner(data, model, metrics=[accuracy, error_rate],
            ...     callback_fns=[partial(
            ...         TrainMetricsRecorder,
            ...         n_batch=len(data.valid_ds)//BATCH_SIZE,
            ...         show_graph=True
            ...     )]
            ... )
    )])

        """
        super().__init__(learn)

        # Check number of batches we will evaluate on with the metrics.
        if n_batch:
            assert n_batch > 0

        self.n_batch = n_batch
        self.show_graph = show_graph
        self.silent = silent

    def on_train_begin(
        self, pbar: PBar, metrics: List, n_epochs: int, **kwargs: Any
    ):
        self.has_metrics = metrics and len(metrics) > 0
        self.has_val = hasattr(self.learn.data, 'valid_ds')

        # Mute recorder. This callback will printout results instead.
        self.learn.recorder.silent = True

        # Result table and graph variables
        self.pbar = pbar
        self.names = ['epoch', 'train_loss']
        if self.has_val:
            self.names.append('valid_loss')

        # Add metrics names
        self.metrics_names = [m_fn.__name__ for m_fn in metrics]
        for m in self.metrics_names:
            self.names.append('train_' + m)
            if self.has_val:
                self.names.append('valid_' + m)
        self.names.append('time')

        if not self.silent:
            self.pbar.write(self.names, table=True)

        self.n_epochs = n_epochs
        self.valid_metrics = []
        self.train_metrics = []

    def on_epoch_begin(self, **kwargs: Any):
        self.start_epoch = time()
        self.y = []  # Target class labels from the last epoch
        self.out = []  # Outputs from the last epoch

    def on_batch_end(
        self,
        train: bool,
        num_batch: int,
        last_target: Tensor,
        last_output: Tensor,
        **kwargs: Any,
    ):
        if (
            train
            and (self.n_batch is None or self.n_batch > num_batch)
            and self.has_metrics
        ):
            self.y.append(last_target.cpu())
            self.out.append(last_output.cpu())

    def on_epoch_end(
        self,
        epoch: int,
        smooth_loss: Tensor,
        metrics: List,
        last_metrics: List,
        pbar: PBar,
        **kwargs: Any,
    ):
        stats = [epoch, smooth_loss]
        if self.has_val:
            stats.append(last_metrics[0])  # validation loss

        if self.has_metrics:
            # Evaluate metrics on the training set
            tr_lm = [
                m_fn(torch.stack(self.out), torch.stack(self.y))
                for m_fn in metrics
            ]
            self.train_metrics.append(tr_lm)

            # Get evaluation metrics on the validation set (computed by learner)
            if self.has_val:
                vl_lm = last_metrics[1:]
                self.valid_metrics.append(vl_lm)

            # Prepare result table values
            for i in range(len(metrics)):
                stats.append(tr_lm[i])
                if self.has_val:
                    stats.append(vl_lm[i])

        # Write to result table
        if not self.silent:
            self._format_stats(stats)

            # Plot (update) metrics for every end of epoch
            if self.show_graph and len(self.train_metrics) > 0:
                self.plot()

    def _format_stats(self, stats: TensorOrNumList) -> None:
        """Format stats before printing. Note, this does the same thing as Recorder's"""
        str_stats = []
        for name, stat in zip(self.names, stats):
            str_stats.append(
                '#na#'
                if stat is None
                else str(stat)
                if isinstance(stat, int)
                else f'{stat:.6f}'
            )
        str_stats.append(format_time(time() - self.start_epoch))
        self.pbar.write(str_stats, table=True)

    def plot(self):
        """Plot metrics graph"""
        if len(self.train_metrics) == 0:
            raise ValueError("No records to plot.")

        # Number of metrics on training set and validation set should be the same
        if len(self.valid_metrics) > 0:
            assert len(self.train_metrics[0]) == len(self.valid_metrics[0])

        # init graph
        if not hasattr(self, 'fig'):
            self.fig, self.axes = plt.subplots(
                len(self.train_metrics[0]),
                1,
                figsize=(6, 4 * len(self.train_metrics[0])),
            )
            self.axes = (
                self.axes.flatten()
                if len(self.train_metrics[0]) > 1
                else [self.axes]
            )
            self.graphs = display(self.fig, display_id=True)

        # Plot each metrics as a subplot
        for i, ax in enumerate(self.axes):
            ax.clear()

            # Plot training set results
            tr_m = [met[i] for met in self.train_metrics]
            x_axis = [i for i in range(len(tr_m))]
            ax.plot(x_axis, tr_m, label="Train")

            # Plot validation set results
            if len(self.valid_metrics) > 0:
                vl_m = [met[i] for met in self.valid_metrics]
                ax.plot(x_axis, vl_m, label="Validation")
            else:
                vl_m = []

            x_bounds = (-0.05, self.n_epochs - 0.95)
            y_bounds = (
                min(-0.05, min(Tensor(tr_m)), min(Tensor(vl_m))) - 0.05,
                max(1.05, max(Tensor(tr_m)), max(Tensor(vl_m))) + 0.05,
            )
            ax.set_xlim(x_bounds)
            ax.set_ylim(y_bounds)

            ax.set_ylabel(self.metrics_names[i])
            ax.set_xlabel("Epochs")
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.legend(loc='upper right')

        plt.close()  # close plot windows. Otherwise two figures are shown at the end
        self.graphs.update(self.fig)

    def last_train_metrics(self):
        """Train set metrics from the last epoch"""
        return self.train_metrics[-1]

    def last_valid_metrics(self):
        """Validation set metrics from the last epoch"""
        return self.valid_metrics[-1]