#!/bin/bash
set -e

# Install Ollama if not present
if ! command -v ollama &> /dev/null; then
  echo "Installing Ollama..."
  brew install ollama
else
  echo "Ollama already installed."
fi

# Start Ollama service if not running
if ! pgrep -x "ollama" > /dev/null; then
  echo "Starting Ollama..."
  ollama serve &> /dev/null &
  sleep 2
fi

# Pull model if not already downloaded
if ! ollama list | grep -q "llama3.2"; then
  echo "Pulling llama3.2..."
  ollama pull llama3.2
else
  echo "llama3.2 already downloaded."
fi

echo "Done."
