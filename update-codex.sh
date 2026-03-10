#!/usr/bin/env bash
set -euo pipefail

# Script para atualizar o Codex em duas modalidades:
#   ./update-codex.sh user  -> atualiza no NVM (usuário)
#   ./update-codex.sh sudo  -> atualiza globalmente (root/sudo)
#   ./update-codex.sh both  -> atualiza user + sudo (padrão)
# Opções:
#   --with-history          -> também remove history.jsonl de ~/.codex e /root/.codex
# Ajuste a versão do Node/NVM se necessário.

NVM_NODE_VERSION="v22.21.1"

user_prefix="$HOME/.nvm/versions/node/$NVM_NODE_VERSION"
include_history=0
mode="both"

usage() {
  cat <<EOF
uso: $0 [user|sudo|both] [--with-history]
sem argumento, atualiza user e sudo
EOF
}

ensure_codex_not_running() {
  local context="$1"
  local warning="[$context] detectado uso do codex; finalize as instâncias em execução antes de atualizar."

  if command -v pgrep >/dev/null 2>&1; then
    if pgrep -x codex >/dev/null 2>&1; then
      echo "$warning"
      exit 1
    fi
  elif ps -eo comm | grep -x codex >/dev/null 2>&1; then
    echo "$warning"
    exit 1
  fi
}

clean_codex_dir() {
  local codex_dir="$1"
  local context="$2"
  local targets=(
    "${codex_dir}/tmp"
    "${codex_dir}/sessions"
    "${codex_dir}/shell_snapshots"
    "${codex_dir}/log"
  )

  if [[ "${include_history}" -eq 1 ]]; then
    targets+=("${codex_dir}/history.jsonl")
  fi

  if [[ ! -d "${codex_dir}" ]]; then
    echo "[$context] nao encontrado: ${codex_dir}"
    return
  fi

  echo "[$context] limpando cache: ${codex_dir}"
  for path in "${targets[@]}"; do
    if [[ -e "${path}" ]]; then
      rm -rf -- "${path}"
      echo "[$context] removido: ${path}"
    else
      echo "[$context] nao encontrado: ${path}"
    fi
  done
}

clean_codex_dir_sudo() {
  local codex_dir="$1"
  local context="$2"
  local targets=(
    "${codex_dir}/tmp"
    "${codex_dir}/sessions"
    "${codex_dir}/shell_snapshots"
    "${codex_dir}/log"
  )

  if [[ "${include_history}" -eq 1 ]]; then
    targets+=("${codex_dir}/history.jsonl")
  fi

  if ! sudo test -d "${codex_dir}"; then
    echo "[$context] nao encontrado: ${codex_dir}"
    return
  fi

  echo "[$context] limpando cache: ${codex_dir}"
  for path in "${targets[@]}"; do
    if sudo test -e "${path}"; then
      sudo rm -rf -- "${path}"
      echo "[$context] removido: ${path}"
    else
      echo "[$context] nao encontrado: ${path}"
    fi
  done
}

run_user() {
  ensure_codex_not_running "user"
  clean_codex_dir "$HOME/.codex" "user"

  echo "[user] limpando dirs quebrados do pacote..."
  rm -rf "$user_prefix/lib/node_modules/@openai/codex" \
         "$user_prefix/lib/node_modules/@openai/.codex-"*

  echo "[user] corrigindo cache npm..."
  mkdir -p "$HOME/.npm"
  chown -R "$(id -u)":"$(id -g)" "$HOME/.npm"
  rm -rf "$HOME/.npm/_cacache" || true
  mkdir -p "$HOME/.npm/_cacache/tmp"
  chown -R "$(id -u)":"$(id -g)" "$HOME/.npm"

  echo "[user] instalando @openai/codex@alpha..."
  npm install -g @openai/codex@alpha

  echo "[user] ajustando permissão do binário..."
  chmod +x "$user_prefix/lib/node_modules/@openai/codex/bin/codex.js" || true
  if [ ! -L "$user_prefix/bin/codex" ]; then
    ln -sf "$user_prefix/lib/node_modules/@openai/codex/bin/codex.js" "$user_prefix/bin/codex"
  fi

  echo "[user] versão instalada:"
  "$user_prefix/bin/codex" --version
}

run_sudo() {
  local sudo_prefix
  ensure_codex_not_running "sudo"

  clean_codex_dir_sudo "/root/.codex" "sudo"

  sudo_prefix=$(sudo npm config get prefix | tr -d '\n')
  echo "[sudo] prefixo detectado: $sudo_prefix"

  echo "[sudo] limpando dirs quebrados do pacote..."
  sudo rm -rf "$sudo_prefix/lib/node_modules/@openai/codex" \
              "$sudo_prefix/lib/node_modules/@openai/.codex-"*

  echo "[sudo] corrigindo cache npm (root)..."
  sudo mkdir -p /root/.npm
  sudo chown -R root:root /root/.npm
  sudo rm -rf /root/.npm/_cacache || true
  sudo mkdir -p /root/.npm/_cacache/tmp
  sudo chown -R root:root /root/.npm

  echo "[sudo] instalando @openai/codex@alpha..."
  sudo npm install -g @openai/codex@alpha

  echo "[sudo] ajustando permissão do binário..."
  sudo chmod +x "$sudo_prefix/lib/node_modules/@openai/codex/bin/codex.js" || true
  if ! sudo test -L "$sudo_prefix/bin/codex"; then
    sudo ln -sf "$sudo_prefix/lib/node_modules/@openai/codex/bin/codex.js" "$sudo_prefix/bin/codex"
  fi

  echo "[sudo] versão instalada:"
  sudo "$sudo_prefix/bin/codex" --version
}

mode_is_set=0
for arg in "$@"; do
  case "$arg" in
    user|sudo|both|all)
      if [[ "${mode_is_set}" -eq 1 && "${mode}" != "$arg" ]]; then
        echo "modo duplicado: $arg"
        usage
        exit 1
      fi
      mode="$arg"
      mode_is_set=1
      ;;
    --with-history)
      include_history=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "argumento invalido: $arg"
      usage
      exit 1
      ;;
  esac
done

if [[ "$mode" == "all" ]]; then
  mode="both"
fi

case "$mode" in
  both)
    run_user
    run_sudo
    ;;
  user)
    run_user
    ;;
  sudo)
    run_sudo
    ;;
  *)
    usage
    exit 1
    ;;
esac
