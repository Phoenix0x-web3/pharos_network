# Phoenix Dev

More info : https://t.me/phoenix_w3

## Pharos Network

Pharos Network is a Layer 1 blockchain focused on Real World Assets (RWA), enabling secure, transparent, and on-chain asset tokenization.

## Functionality
- Daily check in
- Faucet
- Swaps
- Liquidity
- Stake
- Social tasks (twitter)

## Requirements
- Python version 3.11 - 3.12 
- Private keys for EVM wallets
- Proxy (optional)
- Twitter auth tokens (optional) 
- Telegram token for logs (optional) 

## Installation
1. Clone the repository:
```
git clone https://github.com/Phoenix0x-web3/pharos_network
cd pharos_network
```

2. Install dependencies:
```
python install.py
```

3. Activate virtual environment:
```
venv\Scripts\activate
```

4. Run script
```
python main.py
```

## Project Structure
```
pharos_network/
├── data/                   #Web3 intarface
├── files/
|   ├── discord_tokens.txt  # Discord auth token (optional)
|   ├── twitter_tokens.txt  # Twitter auth token (optional)
│   ├── private_keys.txt    # EVM wallet private keys
|   ├── proxy.txt           # Proxy addresses (optional)
|   ├── wallets.db          # Database
│   └── settings.yaml       # Main configuration file
├── functions/              # Functionality
└── utils/                  # Utils
```
## Configuration

### 1. files folder
- `private_keys.txt`: One private key per line
- `proxy.txt`: One proxy per line (format: `http://user:pass@ip:port`)
- `twitter_tokens.txt`: One token per line 
- `discord_tokens.txt`: One token per line 

### 2. Main configurations
```yaml
# Whether to encrypt private keys
private_key_encryption: true

# Number of threads to use for processing wallets
threads: 1

# Number of retries for failed action
retry: 3

# BY DEFAULT: [] - all wallets
# Example: [1, 3, 8] - will run only 1, 3 and 8 wallets
exact_wallets_to_run: []

# Whether to shuffle the list of wallets before processing
shuffle_wallets: true

# Hide wallet address in logs
hide_wallet_address_log: true

# Delay before running the same wallet again after it has completed all actions (7 - 8 hrs default)
random_pause_wallet_after_completion:
  min: 26000
  max: 30000

# Random pause between actions in seconds
random_pause_between_actions:
  min: 20
  max: 30

# Telegram Bot ID for notifications
tg_bot_id: ''

# You can find your chat ID by messaging @userinfobot or using https://web.telegram.org/. (example 1540239116)
tg_user_id: ''
```

### 3. Module Configurations

**Swap / Liquidity**:
```yaml
#swap percent of coin balance
swap_percent:
  min: 5
  max: 30

#liquidity percent of native coin balance
liquidity_percent:
  min: 5
  max: 30

#swaps action count
swaps_count:
  min: 15
  max: 30
```
**Send Token To Friends**:
```yaml
#tips action count
tips_count:
  min: 15
  max: 30
```

**Stake**:
```yaml
#autostake action count
autostake_count:
  min: 1
  max: 4
#Be careful not write a big number, because for one iteraction will be done 3-5 transactions  
```
**Refferals**:
```yaml
# Invite Codes for pharos network, example [invite_code1, invite_code2]
invite_codes: []
```


## Usage

For your security, you can enable private key encryption by setting private_key_encryption: true in the settings. If set to false, encryption will be skipped.

On first use, you need to fill in the `private_keys.txt` file once. After launching the program, go to `DB Actions → Import wallets to Database`.

<img src="https://imgur.com/KdpqzLp.png" alt="Preview" width="600"/>


<img src="https://imgur.com/KZ5tyRK.png" alt="Preview" width="600"/>


If encryption is enabled, you will be prompted to enter and confirm a password. Once completed, your private keys will be deleted from the private_keys.txt file and securely moved to a local database, which is created in the `files` folder.

<img src="https://imgur.com/2J87b4E.png" alt="Preview" width="600"/>

Once the database is created, you can start the project by selecting `Pharos Network → Randomize Activity or Swaps`.

<img src="https://imgur.com/fSXnGE6.png" alt="Preview" width="600"/>

Run All Tasks In Random Order

To decrypt the private keys, enter the password.
<img src="https://imgur.com/RahNzya.png" alt="Preview" width="600"/>

