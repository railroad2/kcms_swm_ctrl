(function () {
    function pinToRowCol(pin, matrixSize) {
        return {
            row: Math.floor(pin / matrixSize),
            col: pin % matrixSize,
        };
    }

    function pinToLabel(pin, matrixSize) {
        const rc = pinToRowCol(pin, matrixSize);
        return `${String.fromCharCode(65 + rc.row)}${String(rc.col).padStart(2, "0")}`;
    }

    class MatrixView {
        constructor(rootElement, options) {
            this.rootElement = rootElement;
            this.matrixSize = options.matrixSize;
            this.cells = [];
            this.rowHeaders = [];
            this.colHeaders = [];
        }

        build() {
            const size = this.matrixSize;

            this.rootElement.className = "matrix-grid";
            this.rootElement.style.gridTemplateColumns = `60px repeat(${size}, 36px)`;

            const corner = document.createElement("div");
            corner.className = "corner-cell";
            this.rootElement.appendChild(corner);

            for (let col = 0; col < size; col++) {
                const header = document.createElement("div");
                header.className = "col-header";
                header.textContent = String(col).padStart(2, "0");
                this.rootElement.appendChild(header);
                this.colHeaders.push(header);
            }

            for (let row = 0; row < size; row++) {
                const rowHeader = document.createElement("div");
                rowHeader.className = "row-header";
                rowHeader.textContent = String.fromCharCode(65 + row);
                this.rootElement.appendChild(rowHeader);
                this.rowHeaders.push(rowHeader);

                const rowCells = [];

                for (let col = 0; col < size; col++) {
                    const cell = document.createElement("div");
                    cell.className = "cell";
                    cell.title = `${String.fromCharCode(65 + row)}${String(col).padStart(2, "0")}`;
                    this.rootElement.appendChild(cell);
                    rowCells.push(cell);
                }

                this.cells.push(rowCells);
            }
        }

        clear() {
            for (let row = 0; row < this.matrixSize; row++) {
                this.rowHeaders[row].classList.remove("active");
            }

            for (let col = 0; col < this.matrixSize; col++) {
                this.colHeaders[col].classList.remove("active");
            }

            for (let row = 0; row < this.matrixSize; row++) {
                for (let col = 0; col < this.matrixSize; col++) {
                    this.cells[row][col].classList.remove("active");
                }
            }
        }

        renderPins(pins) {
            const totalPins = this.matrixSize * this.matrixSize;

            if (!Array.isArray(pins) || pins.length !== totalPins) {
                console.error("Invalid pins payload:", pins);
                return [];
            }

            this.clear();

            const activePins = [];

            for (let pin = 0; pin < totalPins; pin++) {
                if (pins[pin]) {
                    const rc = pinToRowCol(pin, this.matrixSize);
                    this.cells[rc.row][rc.col].classList.add("active");
                    this.rowHeaders[rc.row].classList.add("active");
                    this.colHeaders[rc.col].classList.add("active");
                    activePins.push(pin);
                }
            }

            return activePins;
        }

        activePinsToLabels(activePins) {
            return activePins.map((pin) => pinToLabel(pin, this.matrixSize));
        }
    }

    window.MatrixView = MatrixView;
})();
