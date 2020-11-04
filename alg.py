import copy
import numpy as np
import torch
import torch.nn.functional as F
from copy import deepcopy
import parl

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

__all__ = ['ADER']


class ADER(parl.Algorithm):
    def __init__(
            self,
            model,
            max_action,
            gamma=None,
            tau=None,
            actor_lr=None,
            critic_lr=None,
            policy_noise=0.2,  # Noise added to target policy during critic update
            noise_clip=0.5,  # Range to clip target policy noise
            policy_freq=2, # Frequency of delayed policy updates
            kappa=2,
            epoch=10000,
            alpha=5):  
        assert isinstance(gamma, float)
        assert isinstance(tau, float)
        assert isinstance(actor_lr, float)
        assert isinstance(critic_lr, float)
        self.max_action = max_action
        self.gamma = gamma
        self.tau = tau
        self.actor_lr = actor_lr
        self.critic_lr = critic_lr
        self.policy_noise = policy_noise
        self.noise_clip = noise_clip
        self.policy_freq = policy_freq

        self.kappa = kappa
        self.epoch = epoch
        self.alpha = alpha

        self.model = model.to(device)
        self.target_model = deepcopy(model).to(device)
        self.actor_optimizer = torch.optim.Adam(
            self.model.get_actor_params(), lr=actor_lr)
        self.critic_optimizer = torch.optim.Adam(
            self.model.get_critic_params(), lr=critic_lr)

        self.total_it = 0

    def predict(self, obs):
        return self.model.policy(obs)

    def learn(self, obs, action, reward, next_obs, terminal):
        self.total_it += 1
        # compute explorational coefficient
        train_step = self.total_it
        train_step = (train_step // 100000) * 100000
        t = float(float(self.total_it) / self.epoch)
        coeff = np.sqrt(np.log(t + 2) / (t + 2))
        coeff = self.alpha - self.kappa * coeff
        # coeff = float(self.total_it + 1e4) * 1e-6
        # coeff = 1.0
        with torch.no_grad():
            noise = (torch.randn_like(action) * self.policy_noise).clamp(
                -self.noise_clip, self.noise_clip)

            next_action = (self.target_model.policy(next_obs) + noise).clamp(
                -self.max_action, self.max_action)

            target_Q1, target_Q2 = self.target_model.value(
                next_obs, next_action)

            target = torch.stack((target_Q1, target_Q2), 0)
            target_mean = torch.mean(target, 0)
            target_var = torch.std(target, 0, unbiased=False)

            target_Q = target_mean - coeff * target_var

            target_Q = reward + (1 - terminal) * self.gamma * target_Q

        current_Q1, current_Q2 = self.model.value(obs, action)

        critic_loss = F.mse_loss(current_Q1, target_Q) + F.mse_loss(
            current_Q2, target_Q)

        self.critic_optimizer.zero_grad()
        critic_loss.backward()
        self.critic_optimizer.step()

        if self.total_it % self.policy_freq == 0:

            actor_loss = -self.model.Q1(obs, self.model.policy(obs)).mean()

            self.actor_optimizer.zero_grad()
            actor_loss.backward()
            self.actor_optimizer.step()

            self.sync_target()

    def sync_target(self, decay=None):
        if decay is None:
            decay = 1.0 - self.tau
        for param, target_param in zip(self.model.parameters(),
                                       self.target_model.parameters()):
            target_param.data.copy_((1 - decay) * param.data +
                                    decay * target_param.data)
