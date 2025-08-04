# nama file: bot_pharos_multithread_v2.py

import time
import random
import requests
import json
import concurrent.futures
from web3 import Web3
from web3.exceptions import TransactionNotFound
from eth_account import Account
from eth_account.messages import encode_defunct
import shareithub
from shareithub import shareithub
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from datetime import datetime, timedelta
from rich.live import Live



# ABI Standar untuk token ERC20 (untuk cek saldo dan approve)
ERC20_ABI = json.loads(
    '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"success","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"remaining","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"}]')


# --- BAGIAN KONFIGURASI ---
class Config:
    PRIVATE_KEY_FILE = "privatekey.txt"
    RPC_URL = "https://testnet.dplabs-internal.com/"
    EXPLORER_URL = "https://pharos-testnet.socialscan.io"

    class Login:
        SIGN_MESSAGE = "pharos"
        LOGIN_INVITE_CODE = "S6NGMzXSCDBxhnwo"
        WALLET_NAME = "OKX Wallet"

    class Swap:
        ENABLED = True
        ROUTER_ADDRESS = "0x1a4de519154ae51200b0ad7c90f7fac75547888a"
        AMOUNT_TO_SWAP_EACH = 0.01

        WPHRS_ADDRESS = "0x76aaada469d23216be5f7c596fa25f282ff9b364"

        TARGET_TOKENS = [
            "0x72df0bcd7276f2dfbac900d1ce63c272c4bccced",
            "0xd4071393f8716661958f766df660033b3d35fd29"
        ]
        FEE_TIER = 3000
        DEADLINE_MINUTES = 20

    class Liquidity:
        ENABLED = True
        POSITION_MANAGER_ADDRESS = "0xf8a1d4ff0f9b9af7ce58e1fc1833688f3bfd6115"
        AMOUNT_TO_ADD_PHRS = 0.1

        TOKEN_IDS = {
            "0x72df0bcd7276f2dfbac900d1ce63c272c4bccced": 1234,
            "0xd4071393f8716661958f766df660033b3d35fd29": 501381747380774316
        }


    class Timers:
        DELAY_BETWEEN_SWAPS = (10, 25)
        DELAY_BETWEEN_ITERATIONS = (45, 90)
        DELAY_BEFORE_LIQUIDITY = (15, 30)
        DELAY_FOR_NEXT_RUN = 24 * 60 * 60

    BASE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "Referer": "https://testnet.pharosnetwork.xyz/"
    }


# --- AKHIR BAGIAN KONFIGURASI ---

console = Console()


def generate_random_amount(base_amount):
    random_addition = random.randint(1000, 9999) * 1e-6
    final_amount = base_amount + random_addition
    return final_amount


def load_json_file(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        console.print(
            f"[bold red]❌ ERROR:[/bold red] File '[italic yellow]{file_path}[/italic yellow]' tidak ditemukan.")
        return None
    except json.JSONDecodeError:
        console.print(f"[bold red]❌ ERROR:[/bold red] File '[italic yellow]{file_path}[/italic yellow]' tidak valid.")
        return None


def get_token_balance(w3, token_address, owner_address):
    try:
        token_contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        balance = token_contract.functions.balanceOf(owner_address).call()
        return balance
    except Exception as e:
        console.print(f"[red]   Gagal mendapatkan saldo token {token_address[:10]}...: {e}[/red]")
        return 0


# --- FUNGSI DI BAWAH INI TELAH DIMODIFIKASI UNTUK MENGHAPUS console.status ---
def wait_for_transaction(w3, tx_hash, account_address, action_name):
    """Fungsi baru untuk menunggu transaksi dengan print sederhana, bukan status live."""
    console.print(f"[yellow]      ({account_address[:6]}) Menunggu konfirmasi {action_name}...[/yellow]")
    try:
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        return tx_receipt
    except TransactionNotFound:
        console.print(
            f"[bold red]      ({account_address[:6]}) ❌ Transaksi {action_name} tidak ditemukan (mungkin dibatalkan atau tidak pernah sampai).[/bold red]")
        return None
    except Exception as e:
        console.print(
            f"[bold red]      ({account_address[:6]}) ❌ Error saat menunggu transaksi {action_name}: {e}[/bold red]")
        return None


def approve_token(account, w3, token_address, spender_address, amount_to_approve):
    console.print(
        f"[cyan]   ({account.address[:6]}) Langkah Approve: Memberi izin {spender_address[:10]}... untuk token {token_address[:10]}...[/cyan]")
    token_address_checksum = Web3.to_checksum_address(token_address)
    spender_address_checksum = Web3.to_checksum_address(spender_address)
    token_contract = w3.eth.contract(address=token_address_checksum, abi=ERC20_ABI)

    try:
        allowance = token_contract.functions.allowance(account.address, spender_address_checksum).call()
        if allowance >= amount_to_approve:
            console.print(
                f"[green]      ({account.address[:6]}) ✅ Izin (allowance) sudah cukup. Melewati approve.[/green]")
            return True

        tx_params = {'from': account.address, 'gas': 100000, 'nonce': w3.eth.get_transaction_count(account.address),
                     'gasPrice': w3.eth.gas_price}
        approve_tx = token_contract.functions.approve(spender_address_checksum, amount_to_approve).build_transaction(
            tx_params)
        signed_tx = account.sign_transaction(approve_tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        console.print(
            f"[yellow]      ({account.address[:6]}) 📤 Transaksi approve dikirim! Hash: {tx_hash.hex()[:15]}...[/yellow]")

        tx_receipt = wait_for_transaction(w3, tx_hash, account.address, "approve")

        if tx_receipt and tx_receipt['status'] == 1:
            console.print(f"[bold green]      ({account.address[:6]}) ✅ Approve Berhasil![/bold green]")
            return True
        else:
            console.print(
                f"[bold red]      ({account.address[:6]}) ❌ Approve Gagal! Transaksi Reverted atau Error.[/bold red]")
            return False
    except Exception as e:
        console.print(f"[bold red]      ({account.address[:6]}) ❌ Terjadi error saat proses approve: {e}[/bold red]")
        return False


def perform_swap_v3(account, w3, dex_abi, router_address_str, token_in, token_out, amount_in_wei, is_from_native):
    router_address = Web3.to_checksum_address(router_address_str)
    dex_router_contract = w3.eth.contract(address=router_address, abi=dex_abi)

    params = {
        'tokenIn': Web3.to_checksum_address(token_in),
        'tokenOut': Web3.to_checksum_address(token_out),
        'fee': Config.Swap.FEE_TIER,
        'recipient': account.address,
        'deadline': int(time.time()) + 60 * Config.Swap.DEADLINE_MINUTES,
        'amountIn': amount_in_wei,
        'amountOutMinimum': 0,
        'sqrtPriceLimitX96': 0
    }

    try:
        tx_params = {'from': account.address, 'gas': 400000, 'nonce': w3.eth.get_transaction_count(account.address),
                     'gasPrice': w3.eth.gas_price}
        if is_from_native:
            tx_params['value'] = amount_in_wei

        swap_tx = dex_router_contract.functions.exactInputSingle(params).build_transaction(tx_params)
        signed_tx = account.sign_transaction(swap_tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        console.print(
            f"[yellow]      ({account.address[:6]}) 📤 Transaksi swap dikirim! Hash: {tx_hash.hex()[:15]}...[/yellow]")

        tx_receipt = wait_for_transaction(w3, tx_hash, account.address, "swap")

        if tx_receipt and tx_receipt['status'] == 1:
            console.print(f"[bold green]      ({account.address[:6]}) ✅ Swap Berhasil![/bold green]")
            return True
        else:
            console.print(
                f"[bold red]      ({account.address[:6]}) ❌ Swap Gagal! Transaksi Reverted atau Error.[/bold red]")
            return False
    except Exception as e:
        console.print(f"[bold red]      ({account.address[:6]}) ❌ Terjadi error saat proses swap: {e}[/bold red]")
        return False


def perform_increase_liquidity(account, w3, dex_abi, token_id, token_a, token_b, amount_a_wei, amount_b_wei):
    position_manager_address = Web3.to_checksum_address(Config.Liquidity.POSITION_MANAGER_ADDRESS)
    pm_contract = w3.eth.contract(address=position_manager_address, abi=dex_abi)
    amount0, amount1 = (amount_a_wei, amount_b_wei) if token_a.lower() < token_b.lower() else (
    amount_b_wei, amount_a_wei)

    params = {
        'tokenId': token_id,
        'amount0Desired': amount0,
        'amount1Desired': amount1,
        'amount0Min': 0,
        'amount1Min': 0,
        'deadline': int(time.time()) + 60 * Config.Swap.DEADLINE_MINUTES
    }

    try:
        tx_params = {'from': account.address, 'gas': 800000, 'nonce': w3.eth.get_transaction_count(account.address),
                     'gasPrice': w3.eth.gas_price}
        increase_tx = pm_contract.functions.increaseLiquidity(params).build_transaction(tx_params)
        signed_tx = account.sign_transaction(increase_tx)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        console.print(
            f"[yellow]      ({account.address[:6]}) 📤 Transaksi 'increaseLiquidity' dikirim! Hash: {tx_hash.hex()[:15]}...[/yellow]")

        tx_receipt = wait_for_transaction(w3, tx_hash, account.address, "'increaseLiquidity'")

        if tx_receipt and tx_receipt['status'] == 1:
            console.print(f"[bold green]      ({account.address[:6]}) ✅ Likuiditas Berhasil Ditambahkan![/bold green]")
            return True
        else:
            console.print(
                f"[bold red]      ({account.address[:6]}) ❌ Gagal Menambah Likuiditas! Transaksi Reverted atau Error.[/bold red]")
            return False
    except Exception as e:
        console.print(
            f"[bold red]      ({account.address[:6]}) ❌ Terjadi error saat 'increaseLiquidity': {e}[/bold red]")
        return False


# ... (Fungsi process_account, main, dan lainnya tetap sama seperti versi sebelumnya) ...
def process_account(private_key, index, total, w3, dex_abi, loop_count):
    """Fungsi ini sekarang akan dijalankan di dalam sebuah thread untuk setiap akun."""
    try:
        account = Account.from_key(private_key)
    except Exception:
        console.print(f"[bold red]❌ Private key [Akun {index}] tidak valid. Melewati.[/bold red]")
        return

    console.print(Rule(f"[bold]Memproses Akun {index}/{total} | {account.address}[/bold]"))

    jwt_token = perform_login(account)
    if not jwt_token:
        return
    time.sleep(2)
    perform_daily_signin(account.address, jwt_token)

    for i in range(loop_count):
        console.print(
            Rule(f"[bold magenta]({account.address[:6]}) 🚀 Iterasi Swap ke-{i + 1}/{loop_count} 🚀[/bold magenta]"))

        if Config.Swap.ENABLED:
            random_amount = generate_random_amount(Config.Swap.AMOUNT_TO_SWAP_EACH)
            amount_to_swap_wei = w3.to_wei(random_amount, 'ether')
            console.print(f"[dim]({account.address[:6]}) Jumlah swap acak Zenith: {random_amount:.8f} PHRS[/dim]")

            for target_token in Config.Swap.TARGET_TOKENS:
                console.print(
                    f"[cyan]   ({account.address[:6]}) Zenith Swap: Round Trip untuk Token {target_token[:10]}...[/cyan]")
                swap1_success = perform_swap_v3(account, w3, dex_abi, Config.Swap.ROUTER_ADDRESS,
                                                Config.Swap.WPHRS_ADDRESS, target_token, amount_to_swap_wei, True)
                if not swap1_success:
                    continue
                time.sleep(random.uniform(*Config.Timers.DELAY_BETWEEN_SWAPS))

                balance_to_swap_back = get_token_balance(w3, target_token, account.address)
                if balance_to_swap_back == 0:
                    continue

                approval_success = approve_token(account, w3, target_token, Config.Swap.ROUTER_ADDRESS,
                                                 balance_to_swap_back)
                if not approval_success:
                    continue
                time.sleep(random.uniform(*Config.Timers.DELAY_BETWEEN_SWAPS))

                perform_swap_v3(account, w3, dex_abi, Config.Swap.ROUTER_ADDRESS, target_token,
                                Config.Swap.WPHRS_ADDRESS, balance_to_swap_back, False)
                time.sleep(random.uniform(5, 10))

        if Config.FaroSwap.ENABLED:
            console.print(Rule(f"[bold blue]({account.address[:6]}) FaroSwap: PHRS -> USDT[/bold blue]", style="blue"))
            random_amount_faro = generate_random_amount(Config.FaroSwap.AMOUNT_TO_SWAP)
            amount_to_swap_wei_faro = w3.to_wei(random_amount_faro, 'ether')
            console.print(
                f"[dim]({account.address[:6]}) Jumlah swap acak FaroSwap: {random_amount_faro:.8f} PHRS[/dim]")
            perform_swap_v3(account, w3, dex_abi, Config.FaroSwap.ROUTER_ADDRESS, Config.Swap.WPHRS_ADDRESS,
                            Config.FaroSwap.USDT_ADDRESS, amount_to_swap_wei_faro, True)
            time.sleep(random.uniform(*Config.FaroSwap.DELAY_AFTER_FAROSWAP))

        if i < loop_count - 1:
            delay = random.uniform(*Config.Timers.DELAY_BETWEEN_ITERATIONS)
            console.print(f"[dim]({account.address[:6]}) Jeda iterasi selama {delay:.1f} detik...[/dim]")
            time.sleep(delay)

    if Config.Liquidity.ENABLED:
        console.print(Rule(f"[bold green]({account.address[:6]}) Zenith Liquidity (1x)[/bold green]", style="green"))
        time.sleep(random.uniform(*Config.Timers.DELAY_BEFORE_LIQUIDITY))

        if not Config.Swap.TARGET_TOKENS:
            console.print(
                f"[yellow]({account.address[:6]})   Tidak ada token target untuk ditambah likuiditas.[/yellow]")
        else:
            token_to_add_liquidity_for = Config.Swap.TARGET_TOKENS[0]
            token_id_for_pair = Config.Liquidity.TOKEN_IDS.get(token_to_add_liquidity_for.lower())

            if not token_id_for_pair or token_id_for_pair == 0:
                console.print(
                    f"[bold red]({account.address[:6]})   ❌ GAGAL: Token ID untuk pair {token_to_add_liquidity_for[:10]} tidak ditemukan.[/bold red]")
            else:
                amount_phrs_lp_wei = w3.to_wei(Config.Liquidity.AMOUNT_TO_ADD_PHRS, 'ether')
                initial_target_balance = get_token_balance(w3, token_to_add_liquidity_for, account.address)
                swap_for_lp_success = perform_swap_v3(account, w3, dex_abi, Config.Swap.ROUTER_ADDRESS,
                                                      Config.Swap.WPHRS_ADDRESS, token_to_add_liquidity_for,
                                                      amount_phrs_lp_wei, True)

                if swap_for_lp_success:
                    time.sleep(random.uniform(*Config.Timers.DELAY_BETWEEN_SWAPS))
                    amount_target_token_wei = get_token_balance(w3, token_to_add_liquidity_for,
                                                                account.address) - initial_target_balance

                    if amount_target_token_wei > 0:
                        approve_wphrs_success = approve_token(account, w3, Config.Swap.WPHRS_ADDRESS,
                                                              Config.Liquidity.POSITION_MANAGER_ADDRESS,
                                                              amount_phrs_lp_wei)
                        time.sleep(random.uniform(3, 6))
                        approve_target_success = approve_token(account, w3, token_to_add_liquidity_for,
                                                               Config.Liquidity.POSITION_MANAGER_ADDRESS,
                                                               amount_target_token_wei)

                        if approve_wphrs_success and approve_target_success:
                            time.sleep(random.uniform(*Config.Timers.DELAY_BETWEEN_SWAPS))
                            perform_increase_liquidity(account, w3, dex_abi, token_id_for_pair,
                                                       Config.Swap.WPHRS_ADDRESS, token_to_add_liquidity_for,
                                                       amount_phrs_lp_wei, amount_target_token_wei)


def main():
    console.print(Rule("[bold magenta]🚀 Bot Multi-Thread (Swap & Liquidity) 🚀[/bold magenta]"))
    private_keys = load_private_keys(Config.PRIVATE_KEY_FILE)
    dex_abi = load_json_file('../data/abis/zenith_router.json')
    if not private_keys or not dex_abi:
        console.print("[bold red]Bot berhenti. File penting tidak ada/valid.[/bold red]")
        return

    w3 = Web3(Web3.HTTPProvider(Config.RPC_URL))
    if not w3.is_connected():
        console.print(f"[bold red]Gagal terkoneksi ke RPC Node di {Config.RPC_URL}[/bold red]")
        return
    console.print(f"[green]Terhubung ke RPC Node. Chain ID: {w3.eth.chain_id}[/green]")

    while True:
        try:
            loop_count_str = console.input(
                "[bold yellow]❓ Masukkan jumlah perulangan (loop) swap per akun: [/bold yellow]")
            loop_count = int(loop_count_str)
            if loop_count > 0:
                break
            else:
                console.print("[red]Jumlah perulangan harus lebih dari 0.[/red]")
        except ValueError:
            console.print("[red]Input tidak valid. Harap masukkan angka.[/red]")

    # ===== SESUAIKAN JUMLAH THREADS DI SINI JIKA PERLU =====
    MAX_THREADS = 5  # Direkomendasikan 3-5 untuk menghindari error RPC
    console.print(f"[green]✅ OK! Setiap akun akan melakukan {loop_count} iterasi swap.[/green]")
    console.print(f"[bold blue]🚀 Bot akan berjalan dengan {MAX_THREADS} threads secara paralel.[/bold blue]")

    run_count = 0
    while True:
        run_count += 1
        console.print(Rule(
            f"[bold green]🚀 Memulai Siklus Global ke-{run_count} pada {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 🚀[/bold green]"))

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            future_to_account = {
                executor.submit(process_account, pk, i + 1, len(private_keys), w3, dex_abi, loop_count): f"Akun {i + 1}"
                for i, pk in enumerate(private_keys)
            }

            for future in concurrent.futures.as_completed(future_to_account):
                account_info = future_to_account[future]
                try:
                    future.result()
                except Exception as exc:
                    console.print(f"[bold red]❌ {account_info} menghasilkan error tak terduga: {exc}[/bold red]")

        console.print(Rule("[bold green]✅ Semua Akun Telah Selesai Diproses untuk Siklus Ini[/bold green]"))
        run_countdown(Config.Timers.DELAY_FOR_NEXT_RUN)


def load_private_keys(file_path):
    try:
        with open(file_path, 'r') as f:
            keys = [line.strip() for line in f if line.strip()]
            if not keys:
                console.print(
                    f"[bold red]❌ ERROR:[/bold red] File '[italic yellow]{file_path}[/italic yellow]' kosong.")
                return None
            console.print(f"[bold green]✅ Berhasil memuat {len(keys)} private key.[/bold green]")
            return keys
    except FileNotFoundError:
        console.print(
            f"[bold red]❌ ERROR:[/bold red] File '[italic yellow]{file_path}[/italic yellow]' tidak ditemukan.")
        return None


def perform_login(account):
    console.print(f"[cyan]({account.address[:6]}) Langkah 1: Proses Login...[/cyan]")
    login_url = "https://api.pharosnetwork.xyz/user/login"
    message_to_sign = encode_defunct(text=Config.Login.SIGN_MESSAGE)
    signed_message = account.sign_message(message_to_sign)
    params = {"address": account.address, "signature": signed_message.signature.hex(),
              "wallet": Config.Login.WALLET_NAME, "invite_code": Config.Login.LOGIN_INVITE_CODE}
    headers = Config.BASE_HEADERS.copy()
    headers["Authorization"] = "Bearer null"
    max_retries = 10
    retry_delay = 10
    for attempt in range(max_retries):
        try:
            response = requests.post(login_url, params=params, headers=headers, timeout=20)
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                console.print(
                    f"[red]   ({account.address[:6]}) ❌ Login Gagal. Server memberikan respons tidak valid. Kode Status: {response.status_code}[/red]")
                time.sleep(retry_delay)
                continue
            if response.status_code == 200 and response_data.get("code") == 0:
                console.print(f"[green]   ({account.address[:6]}) ✅ Login berhasil.[/green]")
                return response_data.get("data", {}).get("jwt")
            server_message = response_data.get("msg", "")
            if "1040" in server_message or "too many connections" in server_message.lower():
                console.print(
                    f"[yellow]   ({account.address[:6]}) ⚠️ Login Gagal (Too many connections). Mencoba lagi...[/yellow]")
                time.sleep(retry_delay)
            else:
                console.print(f"[red]   ({account.address[:6]}) ❌ Login Gagal. Server: '{server_message}'.[/red]")
                return None
        except requests.exceptions.RequestException as e:
            console.print(f"[red]   ({account.address[:6]}) ❌ Gagal terhubung ke server login: {e}[/red]")
            time.sleep(retry_delay)
    console.print(
        f"[bold red]({account.address[:6]}) ❌ Login Gagal setelah {max_retries} kali percobaan. Melewati akun ini.[/bold red]")
    return None


def perform_daily_signin(address, jwt_token):
    console.print(f"[cyan]({address[:6]}) Langkah 2: Proses Check-in Harian...[/cyan]")
    signin_url = f"https://api.pharosnetwork.xyz/sign/in?address={address}"
    headers = Config.BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {jwt_token}"
    try:
        response = requests.post(signin_url, headers=headers, timeout=20)
        response_data = response.json()
        if response.status_code == 200 and response_data.get("code") == 0:
            console.print(f"[bold green]   ({address[:6]}) ✅ Check-in Harian Berhasil![/bold green]")
            return True
        msg = response_data.get("msg", "Error")
        if "already" in msg.lower():
            console.print(f"[yellow]   ({address[:6]}) ℹ️  Sudah check-in hari ini.[/yellow]")
            return True
        console.print(f"[red]   ({address[:6]}) ❌ Check-in Gagal. Pesan: '{msg}'[/red]")
        return False
    except requests.exceptions.RequestException as e:
        console.print(f"[red]   ({address[:6]}) ❌ Gagal terhubung ke server check-in: {e}[/red]")
        return False


def run_countdown(duration_seconds):
    end_time = datetime.now() + timedelta(seconds=duration_seconds)
    with Live(console=console, refresh_per_second=1) as live:
        while datetime.now() < end_time:
            remaining = end_time - datetime.now()
            total_seconds = int(remaining.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            live.update(Panel(f"Siklus berikutnya: [bold cyan]{hours:02}:{minutes:02}:{seconds:02}[/bold cyan]",
                              title="[bold green]💤 Waktu Jeda[/bold green]"))
            time.sleep(1)


if __name__ == "__main__":
    main()