# Find jupyter path
jupyter_fullpath=$(which jupyter)
echo $jupyter_fullpath

# Run as sudo
SCRIPT_DIR=$(readlink -f "$0")
BASE_DIR=$(dirname "$SCRIPT_DIR")
sudo $jupyter_fullpath lab $BASE_DIR/.. --allow-root --no-browser --ip=0.0.0.0 --port=18888
