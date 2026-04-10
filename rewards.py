REWARD_INTERVAL = 30  # minutes
REWARD_AMOUNT = 15

def calculate_energy(old_minutes, new_minutes):
    old_rewards = old_minutes // REWARD_INTERVAL
    new_rewards = new_minutes // REWARD_INTERVAL
    return max(0, (new_rewards - old_rewards) * REWARD_AMOUNT)