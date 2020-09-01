#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# =====================================
# @Time    : 2020/8/10
# @Author  : Yang Guan (Tsinghua Univ.)
# @FileName: train_script.py
# =====================================

import argparse
import datetime
import json
import logging
import os

import ray

from buffer import ReplayBuffer, PrioritizedReplayBuffer
from learners.mpg_learner import MPGLearner
from optimizer import OffPolicyAsyncOptimizer
from policy import PolicyWithQs
from trainer import Trainer

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO)

# logging.getLogger().setLevel(logging.INFO)


os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

NAME2LEARNERCLS = dict([('MPG', MPGLearner)])
NAME2BUFFERCLS = dict([('normal', ReplayBuffer), ('priority', PrioritizedReplayBuffer), ('None', None)])
NAME2OPTIMIZERCLS = dict([('OffPolicyAsync', OffPolicyAsyncOptimizer)])


def built_MPG_parser(version):
    parser = argparse.ArgumentParser()

    # trainer
    parser.add_argument('--policy_type', type=str, default='PolicyWithQs')
    parser.add_argument('--buffer_type', type=str, default='normal')
    parser.add_argument('--optimizer_type', type=str, default='OffPolicyAsync')

    # env
    parser.add_argument("--env_id", default='PathTracking-v0')
    parser.add_argument('--num_agent', type=int, default=8)
    parser.add_argument('--num_future_data', type=int, default=10)

    # learner
    parser.add_argument("--alg_name", default='MPG')
    parser.add_argument("--learner_version", default=version)
    parser.add_argument('--sample_num_in_learner', type=int, default=20)
    parser.add_argument('--M', type=int, default=1)
    parser.add_argument('--model_based', default=False)
    parser.add_argument('--num_rollout_list_for_policy_update', type=list, default=[i for i in range(0,20,2)])
    parser.add_argument('--num_rollout_list_for_q_estimation', type=list, default=[i for i in range(0,20,2)])
    parser.add_argument('--deriv_interval_policy', default=False)
    if version == 'MPG-v2':
        parser.add_argument("--eta", type=float, default=0.2)
    parser.add_argument("--gamma", type=float, default=0.98)
    parser.add_argument("--gradient_clip_norm", type=float, default=3)

    # worker
    parser.add_argument('--batch_size', type=int, default=512)
    parser.add_argument("--worker_log_interval", type=int, default=5)

    # buffer
    parser.add_argument('--max_buffer_size', type=int, default=500000)
    parser.add_argument('--replay_starts', type=int, default=3000)
    parser.add_argument('--replay_batch_size', type=int, default=128)
    parser.add_argument('--replay_alpha', type=float, default=0.6)
    parser.add_argument('--replay_beta', type=float, default=0.4)
    parser.add_argument("--buffer_log_interval", type=int, default=100)

    # evaluator
    parser.add_argument("--num_eval_episode", type=int, default=5)

    # policy and model
    parser.add_argument("--policy_lr_schedule", type=list,default=[3e-4, 20000, 3e-6])
    parser.add_argument("--value_lr_schedule", type=list,default=[8e-4, 20000, 8e-6])
    parser.add_argument('--num_hidden_layers', type=int, default=2)
    parser.add_argument('--num_hidden_units', type=int, default=256)
    parser.add_argument('--delay_update', type=int, default=1)
    parser.add_argument('--tau', type=float, default=0.005)
    parser.add_argument("--deterministic_policy", default=True, action='store_true')
    parser.add_argument("--double_Q", default=False, action='store_true')
    parser.add_argument("--target", default=False, action='store_true')

    # preprocessor
    parser.add_argument('--obs_dim', default=None)
    parser.add_argument('--act_dim', default=None)
    parser.add_argument("--obs_preprocess_type", type=str, default='scale')
    num_future_data = parser.parse_args().num_future_data
    parser.add_argument("--obs_scale_factor", type=list, default=[0.2, 1., 2., 1., 2.4, 1/1200] + [1.] * num_future_data)
    parser.add_argument("--reward_preprocess_type", type=str, default='scale')
    parser.add_argument("--reward_scale_factor", type=float, default=0.01)

    # Optimizer (PABAL)
    parser.add_argument('--max_sampled_steps', type=int, default=1000000)
    parser.add_argument('--max_updated_steps', type=int, default=300000)
    parser.add_argument('--num_workers', type=int, default=1)
    parser.add_argument('--num_learners', type=int, default=3)
    parser.add_argument('--num_buffers', type=int, default=2)
    parser.add_argument('--max_weight_sync_delay', type=int, default=300)
    parser.add_argument('--grads_queue_size', type=int, default=5)
    parser.add_argument("--eval_interval", type=int, default=1000)
    parser.add_argument("--save_interval", type=int, default=1000)
    parser.add_argument("--log_interval", type=int, default=1)

    # IO
    time_now = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    results_dir = './results/MPG-v1/experiment-{time}'.format(time=time_now)
    parser.add_argument("--result_dir", type=str, default=results_dir)
    parser.add_argument("--log_dir", type=str, default=results_dir + '/logs')
    parser.add_argument("--model_dir", type=str, default=results_dir + '/models')
    parser.add_argument("--model_load_dir", type=str, default=None)
    parser.add_argument("--model_load_ite", type=int, default=None)
    parser.add_argument("--ppc_load_dir", type=str, default=None)

    # parser.add_argument("--model_load_dir", type=str, default='./results/mixed_pg/experiment-2020-04-22-13-30-57/models')
    # parser.add_argument("--model_load_ite", type=int, default=160)
    # parser.add_argument("--ppc_load_dir", type=str, default='./results/mixed_pg/experiment-2020-04-22-13-30-57/models')

    return parser.parse_args()


def built_parser(alg_name):
    if alg_name == 'TD3':
        return built_TD3_parser()
    elif alg_name == 'SAC':
        return built_SAC_parser()
    elif alg_name == 'MPG-v1':
        return built_MPG_parser('MPG-v1')
    elif alg_name == 'MPG-v2':
        return built_MPG_parser('MPG-v2')
    elif alg_name == 'nstepDPG':
        return built_nstepDPG_parser()
    elif alg_name == 'nstepADP':
        return built_nstepADP_parser()

def main(alg_name):
    args = built_parser(alg_name)
    logger.info('begin training agents with parameter {}'.format(str(args)))
    ray.init(redis_max_memory=1024*1024*1024, object_store_memory=1024*1024*1024)
    os.makedirs(args.result_dir)
    with open(args.result_dir + '/config.json', 'w', encoding='utf-8') as f:
        json.dump(vars(args), f, ensure_ascii=False, indent=4)
    trainer = Trainer(policy_cls=PolicyWithQs,
                      learner_cls=NAME2LEARNERCLS[args.alg_name],
                      buffer_cls=NAME2BUFFERCLS[args.buffer_type],
                      optimizer_cls=NAME2OPTIMIZERCLS[args.optimizer_type],
                      args=args)
    if args.model_load_dir is not None:
        logger.info('loading model')
        trainer.load_weights(args.model_load_dir, args.model_load_ite)
    if args.ppc_load_dir is not None:
        logger.info('loading ppc parameter')
        trainer.load_ppc_params(args.ppc_load_dir)

    trainer.train()


if __name__ == '__main__':
    main('MPG-v1')
