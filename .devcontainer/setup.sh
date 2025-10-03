#!/bin/bash
set -e  # Exit on any error

echo "Updating package lists..."
sudo apt-get update

echo "Installing required packages..."
sudo apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0

echo "Cleaning up..."
sudo rm -rf /var/lib/apt/lists/*

echo "Setup completed successfully!"
