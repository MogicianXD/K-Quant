import os
import os.path
import pathlib

import torch
import numpy as np
import pandas as pd
import qlib
import datetime
from qlib.config import REG_US, REG_CN
from pathlib import Path
import sys

# provider_uri = "~/.qlib/qlib_data/cn_data"  # target_dir
provider_uri = "../../../stock_model/qlib_data/cn_data"  # target_dir
# provider_uri = "~/.qlib/qlib_data/crowd_data"
qlib.init(provider_uri=provider_uri, region=REG_CN)
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP

class DataLoader:

    def __init__(self, df_feature, df_label, df_market_value, df_stock_index, batch_size=800, pin_memory=True,
                 start_index=0, device=None, task=None):

        assert len(df_feature) == len(df_label)

        self.df_feature = df_feature.values
        self.df_label = df_label.values
        self.df_market_value = df_market_value
        self.df_stock_index = df_stock_index
        self.device = device

        if pin_memory:
            self.df_feature = torch.tensor(self.df_feature, dtype=torch.float, device=device)
            if task == 'multi-class':
                self.df_label = torch.tensor(self.df_label, dtype=torch.long, device=device)
            else:
                self.df_label = torch.tensor(self.df_label, dtype=torch.float, device=device)
            # self.df_label = torch.tensor(self.df_label, dtype=torch.float, device=device)
            self.df_market_value = torch.tensor(self.df_market_value, dtype=torch.float, device=device)
            self.df_stock_index = torch.tensor(self.df_stock_index, dtype=torch.long, device=device)

        self.index = df_label.index

        self.batch_size = batch_size
        self.pin_memory = pin_memory
        self.start_index = start_index

        self.daily_count = df_label.groupby(level=0).size().values
        self.daily_index = np.roll(np.cumsum(self.daily_count), 1)
        self.daily_index[0] = 0

    @property
    def batch_length(self):

        if self.batch_size <= 0:
            # this is the default situation
            return self.daily_length

        return len(self.df_label) // self.batch_size

    @property
    def daily_length(self):
        """
        :return:  number of days in the dataloader
        """
        return len(self.daily_count)

    def iter_batch(self):
        if self.batch_size <= 0:
            yield from self.iter_daily_shuffle()
            return

        indices = np.arange(len(self.df_label))
        np.random.shuffle(indices)

        for i in range(len(indices))[::self.batch_size]:
            if len(indices) - i < self.batch_size:
                break
            yield i, indices[i:i + self.batch_size]  # NOTE: advanced indexing will cause copy

    def iter_daily_shuffle(self):
        indices = np.arange(len(self.daily_count))
        np.random.shuffle(indices)
        for i in indices:
            yield i, slice(self.daily_index[i], self.daily_index[i] + self.daily_count[i])

    def iter_daily(self):
        """
        : yield an index and a slice, that from the day
        """
        indices = np.arange(len(self.daily_count))
        for i in indices:
            yield i, slice(self.daily_index[i], self.daily_index[i] + self.daily_count[i])
        # for idx, count in zip(self.daily_index, self.daily_count):
        #     yield slice(idx, idx + count) # NOTE: slice index will not cause copy

    def get(self, slc):
        outs = self.df_feature[slc], self.df_label[slc][:, 0], self.df_market_value[slc], self.df_stock_index[slc]
        # outs = self.df_feature[slc], self.df_label[slc]
        mask = self.padding_mask(outs[0])

        if not self.pin_memory:
            outs = tuple(torch.tensor(x, device=self.device) for x in outs)

        return outs + (self.index[slc], mask, )

    def padding_mask(self, features, max_len=None):
        # Stack and pad features and masks (convert 2D to 3D tensors, i.e. add batch dimension)
        lengths = [X.shape[0] for X in features]  # original sequence length for each time series
        if max_len is None:
            max_len = max(lengths)

        padding_masks = self._padding_mask(torch.tensor(lengths, dtype=torch.int16, device=self.device), max_len=max_len)
        # (batch_size, padded_length) boolean tensor, "1" means keep
        return padding_masks

    @staticmethod
    def _padding_mask(lengths, max_len=None):
        """
        Used to mask padded positions: creates a (batch_size, max_len) boolean mask from a tensor of sequence lengths,
        where 1 means keep element at this position (time step)
        """
        batch_size = lengths.numel()
        max_len = max_len or lengths.max_val()
        return (torch.arange(0, max_len, device=lengths.device)
                .type_as(lengths)
                .repeat(batch_size, 1)
                .lt(lengths.unsqueeze(1)))


class DataLoader_ee:

    def __init__(self, df_feature, df_label, df_market_value, df_embedding, df_stock_index, batch_size=800,
                 pin_memory=True, start_index=0, device=None):

        assert len(df_feature) == len(df_label)

        self.df_feature = df_feature.values
        self.df_label = df_label.values
        self.df_market_value = df_market_value
        self.df_embedding = df_embedding.values
        self.df_stock_index = df_stock_index
        self.device = device

        if pin_memory:
            self.df_feature = torch.tensor(self.df_feature, dtype=torch.float, device=device)
            self.df_label = torch.tensor(self.df_label, dtype=torch.float, device=device)
            self.df_market_value = torch.tensor(self.df_market_value, dtype=torch.float, device=device)
            self.df_stock_index = torch.tensor(self.df_stock_index, dtype=torch.long, device=device)
            self.df_embedding = torch.tensor(self.df_embedding, dtype=torch.float, device=device)

        self.index = df_label.index

        self.batch_size = batch_size
        self.pin_memory = pin_memory
        self.start_index = start_index

        self.daily_count = df_label.groupby(level=0).size().values
        self.daily_index = np.roll(np.cumsum(self.daily_count), 1)
        self.daily_index[0] = 0

    @property
    def batch_length(self):

        if self.batch_size <= 0:
            # this is the default situation
            return self.daily_length

        return len(self.df_label) // self.batch_size

    @property
    def daily_length(self):
        """
        :return:  number of days in the dataloader
        """
        return len(self.daily_count)

    def iter_batch(self):
        if self.batch_size <= 0:
            yield from self.iter_daily_shuffle()
            return

        indices = np.arange(len(self.df_label))
        np.random.shuffle(indices)

        for i in range(len(indices))[::self.batch_size]:
            if len(indices) - i < self.batch_size:
                break
            yield i, indices[i:i + self.batch_size]  # NOTE: advanced indexing will cause copy

    def iter_daily_shuffle(self):
        indices = np.arange(len(self.daily_count))
        np.random.shuffle(indices)
        for i in indices:
            yield i, slice(self.daily_index[i], self.daily_index[i] + self.daily_count[i])

    def iter_daily(self):
        """
        : yield an index and a slice, that from the day
        """
        indices = np.arange(len(self.daily_count))
        for i in indices:
            yield i, slice(self.daily_index[i], self.daily_index[i] + self.daily_count[i])
        # for idx, count in zip(self.daily_index, self.daily_count):
        #     yield slice(idx, idx + count) # NOTE: slice index will not cause copy

    def get(self, slc):
        outs = self.df_feature[slc], self.df_label[slc][:, 0], self.df_market_value[slc], \
               self.df_embedding[slc], self.df_stock_index[slc]
        # outs = self.df_feature[slc], self.df_label[slc]

        if not self.pin_memory:
            outs = tuple(torch.tensor(x, device=self.device) for x in outs)

        return outs + (self.index[slc],)


def create_loaders(args, device):
    """
    load qlib alpha360 data and split into train, validation and test loader
    :param args:
    :return:
    """
    start_time = datetime.datetime.strptime(args.train_start_date, '%Y-%m-%d')
    end_time = datetime.datetime.strptime(args.test_end_date, '%Y-%m-%d')
    train_end_time = datetime.datetime.strptime(args.train_end_date, '%Y-%m-%d')

    """
    Ref($close, -2) / Ref($close, -1) - 1
    or
    Ref($close, -1) / $close - 1
    """
    if args.target == 't+0':
        handler = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
                'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                            'fit_end_time': train_end_time, 'instruments': args.data_set,
                           'infer_processors': [
                        {'class': 'RobustZScoreNorm', 'kwargs': {'fields_group': 'feature', 'clip_outlier': True}},
                        {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}],
                            'learn_processors': [{'class': 'DropnaLabel'},
                                                {'class': 'CSRankNorm', 'kwargs': {'fields_group': 'label'}}],
                            'label': ['Ref($close, -1) / $close - 1']}}
    elif args.target == 'noNorm':
        handler = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
                'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                            'fit_end_time': train_end_time, 'instruments': args.data_set,
                            'label': ['Ref($close, -2) / Ref($close, -1) - 1']}}
    elif args.target == 'week':
        handler = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
                'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                            'fit_end_time': train_end_time, 'instruments': args.data_set, 'infer_processors': [
                        {'class': 'RobustZScoreNorm', 'kwargs': {'fields_group': 'feature', 'clip_outlier': True}},
                        {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}],
                            'learn_processors': [{'class': 'DropnaLabel'},
                                                {'class': 'CSRankNorm', 'kwargs': {'fields_group': 'label'}}],
                            'label': ['Ref($close, -6) / Ref($close, -1) - 1']}}
    else:
        handler = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
                'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                            'fit_end_time': train_end_time, 'instruments': args.data_set, 'infer_processors': [
                        {'class': 'RobustZScoreNorm', 'kwargs': {'fields_group': 'feature', 'clip_outlier': True}},
                        {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}],
                            'learn_processors': [{'class': 'DropnaLabel'},
                                                {'class': 'CSRankNorm', 'kwargs': {'fields_group': 'label'}}],
                            'label': ['Ref($close, -2) / Ref($close, -1) - 1']}}

    segments = {'train': (args.train_start_date, args.train_end_date),
                'valid': (args.valid_start_date, args.valid_end_date),
                'test': (args.test_start_date, args.test_end_date)}
    # get dataset from qlib
    dataset = DatasetH(handler, segments)
    if args.target == 'noNorm':
        df_train, df_valid, df_test = dataset.prepare(["train", "valid", "test"],
                                                      col_set=["feature", "label"], data_key=DataHandlerLP.DK_L, )
        df_train_r, df_valid_r, df_test_r = dataset.prepare(["train", "valid", "test"],
                                                      col_set=["feature", "label"], data_key=DataHandlerLP.DK_R, )
    else:
        df_train, df_valid, df_test = dataset.prepare(["train", "valid", "test"],
                                                      col_set=["feature", "label"],data_key=DataHandlerLP.DK_L, )
    # split those three dataset into train, valid and test
    # import pickle5 as pickle
    import pickle
    with open(args.market_value_path, "rb") as fh:
        # load market value
        df_market_value = pickle.load(fh)
    # df_market_value = pd.read_pickle(args.market_value_path)
    df_market_value = df_market_value / 1000000000
    # market value of every day from 07 to 20
    stock_index = np.load(args.stock_index, allow_pickle=True).item()
    for k, v in stock_index.items():
        if v > 734: stock_index[k] = 733

    start_index = 0
    slc = slice(pd.Timestamp(args.train_start_date), pd.Timestamp(args.train_end_date))
    df_train['market_value'] = df_market_value[slc]
    df_train['market_value'] = df_train['market_value'].fillna(df_train['market_value'].mean())
    df_train['stock_index'] = 733
    df_train['stock_index'] = df_train.index.get_level_values('instrument').map(stock_index).fillna(733).astype(int)
    # the market value and stock_index added to each line
    if args.target == 'noNorm':
        df_train[('bin_label','bins')] = df_train_r[('label', 'Ref($close, -2) / Ref($close, -1) - 1')].apply(lambda x:
                                                                                                      bin_helper(x))
        train_loader = DataLoader(df_train["feature"], df_train["bin_label"], df_train['market_value'],
                                  df_train['stock_index'],batch_size=args.batch_size, pin_memory=args.pin_memory,
                                  start_index=start_index,device=device, task=args.task_name)
    else:
        train_loader = DataLoader(df_train["feature"], df_train["label"], df_train['market_value'],
                                  df_train['stock_index'],batch_size=args.batch_size, pin_memory=args.pin_memory,
                                  start_index=start_index,device=device)

    slc = slice(pd.Timestamp(args.valid_start_date), pd.Timestamp(args.valid_end_date))
    df_valid['market_value'] = df_market_value[slc]
    df_valid['market_value'] = df_valid['market_value'].fillna(df_train['market_value'].mean())
    df_valid['stock_index'] = 733
    df_valid['stock_index'] = df_valid.index.get_level_values('instrument').map(stock_index).fillna(733).astype(int)

    start_index += len(df_valid.groupby(level=0).size())
    if args.target == 'noNorm':
        df_valid[('bin_label', 'bins')] = df_valid_r[('label', 'Ref($close, -2) / Ref($close, -1) - 1')].apply(lambda x:
                                                                                                         bin_helper(x))
        valid_loader = DataLoader(df_valid["feature"], df_valid["bin_label"], df_valid['market_value'],
                                  df_valid['stock_index'], pin_memory=True, start_index=start_index, device=device,
                                  task=args.task_name)
    else:
        valid_loader = DataLoader(df_valid["feature"], df_valid["label"], df_valid['market_value'],
                                  df_valid['stock_index'],pin_memory=True, start_index=start_index, device=device)

    slc = slice(pd.Timestamp(args.test_start_date), pd.Timestamp(args.test_end_date))
    df_test['market_value'] = df_market_value[slc]
    df_test['market_value'] = df_test['market_value'].fillna(df_train['market_value'].mean())
    df_test['stock_index'] = 733
    df_test['stock_index'] = df_test.index.get_level_values('instrument').map(stock_index).fillna(733).astype(int)
    start_index += len(df_test.groupby(level=0).size())
    if args.target == 'noNorm':
        df_test[('bin_label', 'bins')] = df_test_r[('label', 'Ref($close, -2) / Ref($close, -1) - 1')].apply(lambda x:
                                                                                                       bin_helper(x))
        test_loader = DataLoader(df_test["feature"], df_test["bin_label"], df_test['market_value'],
                                 df_test['stock_index'],pin_memory=True, start_index=start_index, device=device,
                                 task=args.task_name)
    else:
        test_loader = DataLoader(df_test["feature"], df_test["label"], df_test['market_value'],
                                 df_test['stock_index'],pin_memory=True, start_index=start_index, device=device)

    return train_loader, valid_loader, test_loader


def create_event_loaders(args, device):
    """
    load qlib alpha360 data and split into train, validation and test loader
    :param args:
    :return:
    """
    start_time = datetime.datetime.strptime(args.train_start_date, '%Y-%m-%d')
    end_time = datetime.datetime.strptime(args.test_end_date, '%Y-%m-%d')
    train_end_time = datetime.datetime.strptime(args.train_end_date, '%Y-%m-%d')

    """
    Ref($close, -2) / Ref($close, -1) - 1
    or
    Ref($close, -1) / $close - 1
    """
    handler = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
            'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                        'fit_end_time': train_end_time, 'instruments': args.data_set, 'infer_processors': [
                    {'class': 'RobustZScoreNorm', 'kwargs': {'fields_group': 'feature', 'clip_outlier': True}},
                    {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}],
                        'learn_processors': [{'class': 'DropnaLabel'},
                                            {'class': 'CSRankNorm', 'kwargs': {'fields_group': 'label'}}],
                        'label': ['Ref($close, -2) / Ref($close, -1) - 1']}}

    segments = {'train': (args.train_start_date, args.train_end_date),
                'valid': (args.valid_start_date, args.valid_end_date),
                'test': (args.test_start_date, args.test_end_date)}
    # get dataset from qlib
    dataset = DatasetH(handler, segments)
    df_train, df_valid, df_test = dataset.prepare(["train", "valid", "test"],
                                                      col_set=["feature", "label"],data_key=DataHandlerLP.DK_L, )
    # split those three dataset into train, valid and test
    # import pickle5 as pickle
    import pickle
    with open(args.market_value_path, "rb") as fh:
        df_market_value = pickle.load(fh)
    df_market_value = df_market_value / 1000000000
    stock_index = np.load(args.stock_index, allow_pickle=True).item()
    with open(args.event_embedding_path,"rb") as fh:
        event_embedding = pickle.load(fh)


    start_index = 0
    slc = slice(pd.Timestamp(args.train_start_date), pd.Timestamp(args.train_end_date))
    df_train['market_value'] = df_market_value[slc]
    df_train['market_value'] = df_train['market_value'].fillna(df_train['market_value'].mean())
    df_train['stock_index'] = 733
    df_train['stock_index'] = df_train.index.get_level_values('instrument').map(stock_index).fillna(733).astype(int)

    df_train['event_embedding'] = event_embedding['embeddings'][slc]
    train_average = df_train['event_embedding'].mean()
    df_train['event_embedding'] = df_train['event_embedding'].apply(lambda x: x if isinstance(x, np.ndarray) else train_average)
    # df_train['event_embedding'] = df_train['event_embedding'].fillna(df_train['event_embedding'].mean())
    train_embedding = df_train['event_embedding'].apply(pd.Series)
    train_embedding.columns = pd.MultiIndex.from_tuples([('embedding', str(i)) for i in range(768)])

    train_loader = DataLoader_ee(df_train["feature"], df_train["label"], df_train['market_value'],
                                 train_embedding['embedding'], df_train['stock_index'],
                                 batch_size=args.batch_size, pin_memory=args.pin_memory, start_index=start_index,
                                 device=device)

    slc = slice(pd.Timestamp(args.valid_start_date), pd.Timestamp(args.valid_end_date))
    df_valid['market_value'] = df_market_value[slc]
    df_valid['market_value'] = df_valid['market_value'].fillna(df_train['market_value'].mean())
    df_valid['stock_index'] = 733
    df_valid['stock_index'] = df_valid.index.get_level_values('instrument').map(stock_index).fillna(733).astype(int)

    df_valid['event_embedding'] = event_embedding['embeddings'][slc]
    valid_average = df_valid['event_embedding'].mean()
    df_valid['event_embedding'] = df_valid['event_embedding'].apply(lambda x: x if isinstance(x, np.ndarray) else valid_average)
    # df_valid['event_embedding'] = df_valid['event_embedding'].fillna(df_valid['event_embedding'].mean())
    valid_embedding = df_valid['event_embedding'].apply(pd.Series)
    valid_embedding.columns = pd.MultiIndex.from_tuples([('embedding', str(i)) for i in range(768)])

    start_index += len(df_valid.groupby(level=0).size())
    valid_loader = DataLoader_ee(df_valid["feature"], df_valid["label"], df_valid['market_value'],
                                 valid_embedding['embedding'], df_valid['stock_index'],
                                 pin_memory=True, start_index=start_index, device=device)

    slc = slice(pd.Timestamp(args.test_start_date), pd.Timestamp(args.test_end_date))
    df_test['market_value'] = df_market_value[slc]
    df_test['market_value'] = df_test['market_value'].fillna(df_train['market_value'].mean())
    df_test['stock_index'] = 733
    df_test['stock_index'] = df_test.index.get_level_values('instrument').map(stock_index).fillna(733).astype(int)

    df_test['event_embedding'] = event_embedding['embeddings'][slc]
    test_average = df_test['event_embedding'].mean()
    df_test['event_embedding'] = df_test['event_embedding'].apply(lambda x: x if isinstance(x, np.ndarray) else test_average)
    test_embedding = df_test['event_embedding'].apply(pd.Series)
    test_embedding.columns = pd.MultiIndex.from_tuples([('embedding', str(i)) for i in range(768)])
    start_index += len(df_test.groupby(level=0).size())
    test_loader = DataLoader_ee(df_test["feature"], df_test["label"], df_test['market_value'],
                                test_embedding['embedding'], df_test['stock_index'],
                                pin_memory=True, start_index=start_index, device=device)

    return train_loader, valid_loader, test_loader


def create_test_loaders(args, param_dict,device):
    """
    return a single dataloader for prediction
    """
    start_time = datetime.datetime.strptime(args.test_start_date, '%Y-%m-%d')
    end_time = datetime.datetime.strptime(args.test_end_date, '%Y-%m-%d')
    start_date = args.test_start_date
    end_date = args.test_end_date
    # 此处fit_start_time参照官方文档和代码
    hanlder = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
               'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                          'fit_end_time': end_time, 'instruments': param_dict['data_set'], 'infer_processors': [
                       {'class': 'RobustZScoreNorm', 'kwargs': {'fields_group': 'feature', 'clip_outlier': True}},
                       {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}],
                          'learn_processors': [{'class': 'DropnaLabel'},
                                               {'class': 'CSRankNorm', 'kwargs': {'fields_group': 'label'}}],
                          'label': ['Ref($close, -2) / Ref($close, -1) - 1']}}
    segments = {'test': (start_date, end_date)}
    dataset = DatasetH(hanlder, segments)
    # prepare return a list of df, df_test is the first one
    df_test = dataset.prepare(["test"], col_set=["feature", "label"], data_key=DataHandlerLP.DK_L, )[0]
    # ----------------------------------------
    # import pickle5 as pickle
    import pickle
    # only HIST need this
    with open(param_dict['market_value_path'], "rb") as fh:
        # load market value
        df_market_value = pickle.load(fh)
        # the df_market_value save
    df_market_value = df_market_value / 1000000000
    stock_index = np.load(param_dict['stock_index'], allow_pickle=True).item()
    # stock_index is a dict and stock is the key, index is the value
    start_index = 0

    slc = slice(pd.Timestamp(start_date), pd.Timestamp(end_date))
    df_test['market_value'] = df_market_value[slc]
    df_test['market_value'] = df_test['market_value'].fillna(df_test['market_value'].mean())
    df_test['stock_index'] = 733
    df_test['stock_index'] = df_test.index.get_level_values('instrument').map(stock_index).fillna(733).astype(int)
    start_index += len(df_test.groupby(level=0).size())

    test_loader = DataLoader(df_test["feature"], df_test["label"], df_test['market_value'], df_test['stock_index'],
                             pin_memory=True, start_index=start_index, device=device)
    return test_loader


def create_incre_loaders(args, param_dict, device):
    """
    load qlib alpha360 data and split into train, validation and test loader
    :param args:
    :return:
    """
    start_time = datetime.datetime.strptime(args.incre_start_date, '%Y-%m-%d')
    end_time = datetime.datetime.strptime(args.incre_end_date, '%Y-%m-%d')
    start_date = args.incre_start_date
    end_date = args.incre_end_date
    incre_end_time = datetime.datetime.strptime(args.incre_end_date, '%Y-%m-%d')
    if param_dict['target'] == 't+0':
        hanlder = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
                   'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                              'fit_end_time': end_time, 'instruments': param_dict['data_set'], 'infer_processors': [
                           {'class': 'RobustZScoreNorm', 'kwargs': {'fields_group': 'feature', 'clip_outlier': True}},
                           {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}],
                              'learn_processors': [{'class': 'DropnaLabel'},
                                                   {'class': 'CSRankNorm', 'kwargs': {'fields_group': 'label'}}],
                              'label': ['Ref($close, -1) / $close - 1']}}
    else:
        handler = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
                'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                            'fit_end_time': incre_end_time, 'instruments': param_dict['data_set'], 'infer_processors': [
                        {'class': 'RobustZScoreNorm', 'kwargs': {'fields_group': 'feature', 'clip_outlier': True}},
                        {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}],
                            'learn_processors': [{'class': 'DropnaLabel'},
                                                {'class': 'CSRankNorm', 'kwargs': {'fields_group': 'label'}}],
                            'label': ['Ref($close, -2) / Ref($close, -1) - 1']}}

    segments = {'incre': (args.incre_start_date, args.incre_end_date)}
    # get dataset from qlib
    dataset = DatasetH(handler, segments)

    df_incre = dataset.prepare(["incre"], col_set=["feature", "label"], data_key=DataHandlerLP.DK_L, )[0]

    import pickle
    # only HIST need this
    with open(param_dict['market_value_path'], "rb") as fh:
        # load market value
        df_market_value = pickle.load(fh)
        # the df_market_value save
    df_market_value = df_market_value / 1000000000
    stock_index = np.load(param_dict['stock_index'], allow_pickle=True).item()
    # stock_index is a dict and stock is the key, index is the value
    start_index = 0

    slc = slice(pd.Timestamp(start_date), pd.Timestamp(end_date))
    df_incre['market_value'] = df_market_value[slc]
    df_incre['market_value'] = df_incre['market_value'].fillna(df_incre['market_value'].mean())
    df_incre['stock_index'] = 733
    df_incre['stock_index'] = df_incre.index.get_level_values('instrument').map(stock_index).fillna(733).astype(int)
    start_index += len(df_incre.groupby(level=0).size())

    incre_loader = DataLoader(df_incre["feature"], df_incre["label"], df_incre['market_value'], df_incre['stock_index'],
                              batch_size=param_dict['batch_size'], pin_memory=param_dict['pin_memory'], start_index=start_index, device=device)
    return incre_loader


def create_incre_pre_loaders(args, param_dict, device):
    """
    load qlib alpha360 data and split into train, validation and test loader
    :param args:
    :return:
    """
    start_time = datetime.datetime.strptime(param_dict['train_start_date'], '%Y-%m-%d')
    end_time = datetime.datetime.strptime(param_dict['train_end_date'], '%Y-%m-%d')
    start_date = param_dict['train_start_date']
    end_date = param_dict['train_end_date']


    if param_dict['target'] == 't+0':
        hanlder = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
                   'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                              'fit_end_time': end_time, 'instruments': param_dict['data_set'], 'infer_processors': [
                           {'class': 'RobustZScoreNorm', 'kwargs': {'fields_group': 'feature', 'clip_outlier': True}},
                           {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}],
                              'learn_processors': [{'class': 'DropnaLabel'},
                                                   {'class': 'CSRankNorm', 'kwargs': {'fields_group': 'label'}}],
                              'label': ['Ref($close, -1) / $close - 1']}}

    else:
        handler = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
                'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                            'fit_end_time': end_time, 'instruments': param_dict['data_set'], 'infer_processors': [
                        {'class': 'RobustZScoreNorm', 'kwargs': {'fields_group': 'feature', 'clip_outlier': True}},
                        {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}],
                            'learn_processors': [{'class': 'DropnaLabel'},
                                                {'class': 'CSRankNorm', 'kwargs': {'fields_group': 'label'}}],
                            'label': ['Ref($close, -2) / Ref($close, -1) - 1']}}

    segments = {'incre': (start_date, end_date)}
    # get dataset from qlib
    dataset = DatasetH(handler, segments)

    df_incre = dataset.prepare(["incre"], col_set=["feature", "label"], data_key=DataHandlerLP.DK_L, )[0]

    import pickle
    # only HIST need this
    with open(param_dict['market_value_path'], "rb") as fh:
        # load market value
        df_market_value = pickle.load(fh)
        # the df_market_value save
    df_market_value = df_market_value / 1000000000
    stock_index = np.load(param_dict['stock_index'], allow_pickle=True).item()
    # stock_index is a dict and stock is the key, index is the value
    start_index = 0

    slc = slice(pd.Timestamp(start_date), pd.Timestamp(end_date))
    df_incre['market_value'] = df_market_value[slc]
    df_incre['market_value'] = df_incre['market_value'].fillna(df_incre['market_value'].mean())
    df_incre['stock_index'] = 733
    df_incre['stock_index'] = df_incre.index.get_level_values('instrument').map(stock_index).fillna(733).astype(int)
    start_index += len(df_incre.groupby(level=0).size())

    incre_pre_loader = DataLoader(df_incre["feature"], df_incre["label"], df_incre['market_value'], df_incre['stock_index'],
                              batch_size=param_dict['batch_size'], pin_memory=param_dict['pin_memory'], start_index=start_index, device=device)
    return incre_pre_loader


def bin_helper(x):
    if x < -0.05:
        return 0
    elif x < 0:
        return 1
    elif x < 0.05:
        return 2
    else:
        return 3
    # if x < -0.05:
    #     return 0
    # elif x < -0.04:
    #     return 1
    # elif x < -0.03:
    #     return 2
    # elif x < -0.02:
    #     return 3
    # elif x < -0.01:
    #     return 4
    # elif x < 0:
    #     return 5
    # elif x < 0.01:
    #     return 6
    # elif x < 0.02:
    #     return 7
    # elif x < 0.03:
    #     return 8
    # elif x < 0.04:
    #     return 9
    # elif x < 0.05:
    #     return 10
    # else:
    #     return 11


def create_doubleadapt_loaders(args, rank_label=True, save=True, reload=True):
    """
    load qlib alpha360 data and split into train, validation and test loader
    :param args:
    :return:
    """
    start_time = datetime.datetime.strptime(args.incre_train_start, '%Y-%m-%d')
    end_time = datetime.datetime.strptime(args.test_end, '%Y-%m-%d')
    train_end_time = datetime.datetime.strptime(args.incre_val_end, '%Y-%m-%d')

    handler = {'class': 'Alpha360', 'module_path': 'qlib.contrib.data.handler',
            'kwargs': {'start_time': start_time, 'end_time': end_time, 'fit_start_time': start_time,
                        'fit_end_time': train_end_time, 'instruments': 'csi300', 'infer_processors': [
                    {'class': 'RobustZScoreNorm', 'kwargs': {'fields_group': 'feature', 'clip_outlier': True}},
                    {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}],
                        'learn_processors': [{'class': 'DropnaLabel'},
                                            {'class': "CSRankNorm" if rank_label else "CSZScoreNorm",
                                             'kwargs': {'fields_group': 'label'}}],
                        'label': ['Ref($close, -2) / Ref($close, -1) - 1']}}

    segments = {
        'train': (args.incre_train_start, args.test_end)
    }
    DIRNAME = Path(__file__).absolute().resolve().parent
    h_path = DIRNAME / "handlers" / f"csi300_rank{rank_label}_alpha360_handler_horizon1"
    if not os.path.exists(h_path):
        os.makedirs(h_path)
    h_path = h_path / f"{args.test_end}.pkl"

    # get dataset from qlib
    if reload:
        if os.path.exists(h_path):
            handler = f"file://{h_path}"
        else:
            for file in h_path.parent.iterdir():
                if pd.Timestamp(file.name[:-4]) >= pd.Timestamp(args.test_end):
                    h_path = file.absolute()
                    handler = f"file://{h_path}"
                else:
                    os.remove(file.absolute())
    dataset = DatasetH(handler, segments)

    if save and not isinstance(handler, str):
        dataset.handler.to_pickle(h_path, dump_all=True)
        print('Save handler file to', h_path)

    return dataset

