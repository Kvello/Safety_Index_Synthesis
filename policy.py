from model import MLPNet
import numpy as np
from gym import spaces
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.optimizers.schedules import PolynomialDecay


class PolicyWithValue(object):
    import tensorflow as tf

    def __init__(self, obs_space, act_space, args):
        self.args = args
        assert isinstance(obs_space, spaces.Box)
        assert isinstance(act_space, spaces.Box) or isinstance(act_space, spaces.Discrete)
        obs_dim = obs_space.shape[0] if args.obs_dim is None else self.args.obs_dim
        if isinstance(act_space, spaces.Discrete):
            self.act_dist_cls = DiscreteDistribution
            act_dim = act_space.n if args.act_dim is None else self.args.act_dim
        else:
            self.act_dist_cls = GuassianDistribution
            act_dim = act_space.shape[0] * 2 if args.act_dim is None else self.args.act_dim * 2
        self.policy = MLPNet(obs_dim, 2, 128, act_dim)
        self.value = MLPNet(obs_dim, 2, 128, 1)
        self.models = [self.policy, self.value]
        policy_lr_schedule = self.tf.keras.optimizers.schedules.PolynomialDecay(*self.args.policy_lr_schedule)
        value_lr_schedule = self.tf.keras.optimizers.schedules.PolynomialDecay(*self.args.value_lr_schedule)
        self.policy_optimizer = self.tf.keras.optimizers.Adam(policy_lr_schedule)
        self.value_optimizer = self.tf.keras.optimizers.Adam(value_lr_schedule)
        self.optimizers = [self.policy_optimizer, self.value_optimizer]

    def save_weights(self, save_dir, iteration):
        for model in self.models:
            model.save_weights(save_dir + '/' + model.name + 'ite' + str(iteration))

    def load_weights(self, load_dir, iteration):
        for model in self.models:
            model.load_weights(load_dir + '/' + model.name + 'ite' + str(iteration))

    def get_weights(self):
        return [model.get_weights() for model in self.models]

    @property
    def trainable_weights(self):
        return self.tf.nest.flatten([model.trainable_weights for model in self.models])

    def set_weights(self, weights):
        for i, weight in enumerate(weights):
            self.models[i].set_weights(weight)

    def apply_gradients(self, iteration, grads):
        gradi_start = 0
        for i in range(len(self.models)):
            len_weights = len(self.models[i].trainable_weights)
            gradi_end = gradi_start + len_weights
            self.optimizers[i].apply_gradients(zip(grads[gradi_start: gradi_end], self.models[i].trainable_weights))
            gradi_start = gradi_end

    def compute_action(self, obs):
        logits = self.policy(obs)
        act_dist = self.act_dist_cls(logits)
        action = act_dist.sample()
        neglogp = act_dist.neglogp(action)

        return action, neglogp

    def compute_neglogp(self, obs, action):
        # print(action)
        logits = self.policy(obs)
        assert not np.isnan(logits[0][0])

        act_dist = self.act_dist_cls(logits)
        # assert not np.isnan(neglogp[0][0])

        return act_dist.neglogp(action)

    def compute_vf(self, obs):
        return self.value(obs)


class PolicyWithQs(object):
    import tensorflow as tf

    def __init__(self, obs_space, act_space, args):
        self.args = args
        assert isinstance(obs_space, spaces.Box)
        assert isinstance(act_space, spaces.Box)
        obs_dim = obs_space.shape[0] if args.obs_dim is None else self.args.obs_dim
        self.act_dist_cls = GuassianDistribution
        act_dim = act_space.shape[0] if args.act_dim is None else self.args.act_dim
        self.policy = MLPNet(obs_dim, 2, 128, act_dim * 2, name='policy')
        self.policy_target = MLPNet(obs_dim, 2, 128, act_dim * 2, name='policy_target')
        policy_lr_schedule = PolynomialDecay(*self.args.policy_lr_schedule)
        self.policy_optimizer = self.tf.keras.optimizers.Adam(policy_lr_schedule, name='policy_adam_opt')

        self.Qs = tuple(MLPNet(obs_dim + act_dim, 2, 128, 1, name='Q' + str(i)) for i in range(self.args.Q_num))
        self.Q_targets = tuple(
            MLPNet(obs_dim + act_dim, 2, 128, 1, name='Q_target' + str(i)) for i in range(self.args.Q_num))
        for Q, Q_target in zip(self.Qs, self.Q_targets):
            source_params = Q.get_weights()
            Q_target.set_weights(source_params)

        self.Q_optimizers = tuple(self.tf.keras.optimizers.Adam(self.tf.keras.optimizers.schedules.PolynomialDecay(
            *self.args.value_lr_schedule)) for _ in range(len(self.Qs)))

        if self.args.log_alpha == 'auto':
            self.log_alpha = self.tf.Variable(self.args.init_log_alpha, dtype=self.tf.float32, name='log_alpha')
            log_alpha_lr_schedule = self.tf.keras.optimizers.schedules.PolynomialDecay(*self.args.log_alpha_lr_schedule)
            self.log_alpha_optimizer = self.tf.keras.optimizers.Adam(log_alpha_lr_schedule, name='log_alpha_adam_opt')
            self.models = self.Qs + (self.policy, self.log_alpha,)
            self.optimizers = self.Q_optimizers + (self.policy_optimizer, self.log_alpha_optimizer)

        else:
            self.log_alpha = self.args.log_alpha
            self.models = self.Qs + (self.policy,)
            self.optimizers = self.Q_optimizers + (self.policy_optimizer,)

    def save_weights(self, save_dir, iteration):
        model_pairs = [(model.name, model) for model in self.models]
        optimizer_pairs = [(optimizer._name, optimizer) for optimizer in self.optimizers]
        ckpt = self.tf.train.Checkpoint(**dict(model_pairs + optimizer_pairs))
        ckpt.save(save_dir + '/ckpt_ite' + str(iteration))

    def load_weights(self, load_dir, iteration):
        model_pairs = [(model.name, model) for model in self.models]
        optimizer_pairs = [(optimizer._name, optimizer) for optimizer in self.optimizers]
        ckpt = self.tf.train.Checkpoint(**dict(model_pairs + optimizer_pairs))
        ckpt.restore(load_dir + '/ckpt_ite' + str(iteration))

    def get_weights(self):
        return [model.get_weights() if hasattr(model, 'get_weights') else model for model in self.models]

    @property
    def trainable_weights(self):
        return self.tf.nest.flatten(
            [model.trainable_weights if hasattr(model, 'trainable_weights') else [model] for model in self.models])

    def set_weights(self, weights):
        for i, weight in enumerate(weights):
            if hasattr(self.models[i], 'set_weights'):
                self.models[i].set_weights(weight)
            else:
                self.models[i].assign(weight)

    def apply_gradients(self, iteration, grads):
        for i in range(self.args.Q_num):
            weights = self.models[i].trainable_weights
            len_weights = len(weights)
            self.optimizers[i].apply_gradients(zip(grads[i*len_weights:(i+1)*len_weights], weights))
        if iteration % self.args.delay_update == 0:
            gradi_start = len(self.models[0].trainable_weights) * self.args.Q_num
            for i in range(self.args.Q_num, len(self.models)):
                weights = self.models[i].trainable_weights if hasattr(self.models[i], 'trainable_weights') \
                    else [self.models[i]]
                gradi_end = gradi_start + len(weights)
                self.optimizers[i].apply_gradients(zip(grads[gradi_start:gradi_end], weights))
                gradi_start = gradi_end
            self.update_policy_target()
            self.update_Q_targets()

    def update_Q_targets(self):
        tau = self.args.tau
        for Q, Q_target in zip(self.Qs, self.Q_targets):
            source_params = Q.get_weights()
            target_params = Q_target.get_weights()
            Q_target.set_weights([
                tau * source + (1.0 - tau) * target
                for source, target in zip(source_params, target_params)
            ])

    def update_policy_target(self):
        tau = self.args.tau
        source_params = self.policy.get_weights()
        target_params = self.policy_target.get_weights()
        self.policy.set_weights([
            tau * source + (1.0 - tau) * target
            for source, target in zip(source_params, target_params)
        ])

    def compute_action(self, obs):
        logits = self.policy(obs)

        act_dist = self.act_dist_cls(logits)
        action = act_dist.sample()
        neglogp = act_dist.neglogp(action)
        return action, neglogp

    def compute_logits(self, obs):
        return self.policy(obs)

    def compute_neglogp(self, obs, act):
        logits = self.policy(obs)
        act_dist = self.act_dist_cls(logits)
        return act_dist.neglogp(act)

    def compute_Qs(self, obs, act):
        Q_inputs = self.tf.concat([obs, act], axis=-1)
        # print(self.tf.shape(obs), self.tf.shape(act), self.tf.shape(Q_inputs))
        # print(self.tf.shape(self.Qs[0](Q_inputs)))
        return [Q(Q_inputs) for Q in self.Qs]

    def compute_Q_targets(self, obs, act):
        Q_inputs = self.tf.concat([obs, act], axis=-1)
        return [Q_target(Q_inputs) for Q_target in self.Q_targets]

    def get_log_alpha(self):
        return self.log_alpha


class GuassianDistribution(object):
    import tensorflow as tf

    def __init__(self, logits):
        self.mean, self.logstd = self.tf.split(logits, num_or_size_splits=2, axis=-1)
        self.std = self.tf.exp(self.logstd)

    def mode(self):
        return self.mean

    def sample(self):
        return self.mean + self.std * self.tf.random.normal(self.tf.shape(self.mean))

    def neglogp(self, sample):
        return 0.5 * self.tf.reduce_sum(self.tf.square((sample - self.mean) / self.std), axis=-1) \
               + 0.5 * self.tf.math.log(2.0 * np.pi) * self.tf.cast(self.tf.shape(sample)[-1], self.tf.float32) \
               + self.tf.reduce_sum(self.logstd, axis=-1)

    def entropy(self):
        return self.tf.reduce_sum(self.logstd + 0.5 * self.tf.math.log(2.0 * np.pi * np.e), axis=-1)

    def kl_divergence(self, other_gauss):  # KL(this_dist, other_dist)
        assert isinstance(other_gauss, GuassianDistribution)
        return self.tf.reduce_sum(other_gauss.logstd - self.logstd + (
                self.tf.square(self.std) + self.tf.square(self.mean - other_gauss.mean)) / (
                                          2.0 * self.tf.square(other_gauss.std)) - 0.5, axis=-1)


class DiscreteDistribution(object):
    import tensorflow as tf

    def __init__(self, logits):
        self.logits = logits

    def mode(self):
        return self.tf.argmax(self.logits, axis=-1)

    @property
    def mean(self):
        return self.tf.nn.softmax(self.logits)

    def neglogp(self, x):
        x = self.tf.one_hot(x, self.logits.get_shape().as_list()[-1])
        return self.tf.compat.v1.nn.softmax_cross_entropy_with_logits_v2(
            logits=self.logits,
            labels=x)

    def kl(self, other):
        a0 = self.logits - self.tf.reduce_max(self.logits, axis=-1, keepdims=True)
        a1 = other.logits - self.tf.reduce_max(other.logits, axis=-1, keepdims=True)
        ea0 = self.tf.exp(a0)
        ea1 = self.tf.exp(a1)
        z0 = self.tf.reduce_sum(ea0, axis=-1, keepdims=True)
        z1 = self.tf.reduce_sum(ea1, axis=-1, keepdims=True)
        p0 = ea0 / z0
        return self.tf.reduce_sum(p0 * (a0 - self.tf.math.log(z0) - a1 + self.tf.math.log(z1)), axis=-1)

    def entropy(self):
        a0 = self.logits - self.tf.reduce_max(self.logits, axis=-1, keepdims=True)
        ea0 = self.tf.exp(a0)
        z0 = self.tf.reduce_sum(ea0, axis=-1, keepdims=True)
        p0 = ea0 / z0
        return self.tf.reduce_sum(p0 * (self.tf.math.log(z0) - a0), axis=-1)

    def sample(self):
        u = self.tf.random.uniform(self.tf.shape(self.logits), dtype=self.logits.dtype)
        return self.tf.argmax(self.logits - self.tf.math.log(-self.tf.math.log(u)), axis=-1)


def test_policy():
    import gym
    from train_script import built_mixedpg_parser
    args = built_mixedpg_parser()
    print(args.obs_dim, args.act_dim)
    env = gym.make('PathTracking-v0')
    policy = PolicyWithQs(env.observation_space, env.action_space, args)
    obs = np.random.random((128, 6))
    act = np.random.random((128, 2))
    Qs = policy.compute_Qs(obs, act)
    print(Qs)

def test_policy2():
    from train_script import built_mixedpg_parser
    import gym
    args = built_mixedpg_parser()
    env = gym.make('Pendulum-v0')
    policy_with_value = PolicyWithQs(env.observation_space, env.action_space, args)


if __name__ == '__main__':
    test_policy2()
