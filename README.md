# KCMS switching matrix control software

## Usage

* Setup a raspberry pi pico.
    * Setup a raspberry pico to use micropython
        * see `https://micropython.org/download/RPI_PICO2/`
    * Install the mpremote
        * `pip install mpremote`
    * Copy the scripts in `pico_micropython/` 
        * `bash pico_micropython/upload.sh`
    * Reset the RPi pico
        * `$ mpremote reset`

* Set the gateway
    * Set the UART communication between the raspberry pi (gateway) and the RPi pico.
    * modify the path of ExecStart in the `websocket_server/ws-gateway.service` file.
    * copy ws-gateway.service in /etc/systemd/system/
    * Run daemon
        * `$ sudo systemctl daemon-reload`
        * `$ sudo systemctl enable ws-gateway`
        * `$ sudo systemctl start ws-gateway`
    * To see the log
        * `$ journalctl -u ws-gateway`
    * The websocket IRL is `ws://<server ip>:8765`. 
    
* switching matrix control
    * `daq_client$ python3 sw_control.py --help`

* UART client of RPi pico
    * `pico_uart_client`
    * for debugging
    

