var thisApp;
var app = new Vue({
    el: '#app',
    delimiters: ["[[", "]]"],
    data: {
        boundaryCheckFlag: true,
        message: "",
        workspaceSizeMm: {"x": 0.0, "y": 0.0},
        pixelSizeMm: {"x": 0.0, "y": 0.0},
        outputResolution: {"x": 0, "y": 0},
        originalPointCoordinates: {"x": 0.0, "y": 0.0},
        plotterState: "",
        plotterPosition: {"x": 0.0, "y": 0.0, "z": 0.0},
        xyFactors: {"x": 0.0, "y": 0.0},
        targetPoint: {"x": 0.0, "y": 0.0},
        targetPositionMm: {"x": 0.0, "y": 0.0},
        imageWidth: 1000,
        imageHeight: 500,

        csrfToken: null,
        api: "http://localhost:8000/plotter/",
        endpoints: {
            "image": "image",
            "metadata": "metadata",
            "move": "move",
            "unlock": "unlock",
            "setzero": "zero",
        }
    },
    methods: {
        drawTargetPoint: function (ctx) {
            // Draw a circle in the clicked point.
            ctx.fillStyle = "#033dfc"; // Red color

            ctx.beginPath(); //Start path
            ctx.arc(this.targetPoint.x + 0.5, this.targetPoint.y + 0.5, 3, 0, Math.PI * 2, true); // Draw a point using the arc function of the canvas with a point structure.
            ctx.fill(); // Close the path and fill.
        },
        unlockPlotter: function () {
            fetch(this.api + this.endpoints.unlock);
        },
        getMetadata: function () {
            fetch(this.api + this.endpoints.metadata)
                .then(response => {
                    response.json().then(data => {
                        // Set metadata.
                        this.workspaceSizeMm = data["workspace_size_mm"];
                        this.pixelSizeMm = data["pixel_size_mm"];
                        this.outputResolution = data["output_resolution"];
                        this.originalPointCoordinates = data["original_point_coordinates"];
                        this.xyFactors = data["xy_factors"];
                    });
                });
        },
        setApi: function () {
            // Validate URL.
            newApi = document.getElementById("api-input").value;
            if (validURL(newApi)) {
                this.api = newApi;
                this.getMetadata();
                this.message = "API updated.";
            } else {
                // DEBUG.
                // this.api = newApi;
                // this.getMetadata();
                this.message = "Invalid URL";
            }
        },
        convertToPx: function (x, y) {
            return {
                "x": x * this.xyFactors.x + this.originalPointCoordinates.x,
                "y": y * this.xyFactors.y + this.originalPointCoordinates.y
            };
        },
        convertToMm: function (x, y) {
            return {
                "x": (x - this.originalPointCoordinates.x) / this.xyFactors.x,
                "y": (y - this.originalPointCoordinates.y) / this.xyFactors.y
            };
        },
        movePlotter: function (newPosition, type) {
            if (type === "incremental") {
                this.targetPositionMm.x += newPosition.x;
                this.targetPositionMm.y += newPosition.y;
            } else {
                this.targetPositionMm = newPosition;
            }
            this.targetPoint = this.convertToPx(this.targetPositionMm.x, this.targetPositionMm.y);

            // Sanity check.
            if (this.boundaryCheckFlag) {
                if ((this.targetPositionMm.x <= this.workspaceSizeMm.x) && (this.targetPositionMm.y <= this.workspaceSizeMm.y)
                && (this.targetPositionMm.x >= 0) && (this.targetPositionMm.y >= 0)) {
                this.message = "Normal";
                } else {
                    this.message = "Out of workspace boundary.";
                    return;
                }
            }

            fetch(thisApp.api + thisApp.endpoints.move,
                {
                    method: "post",
                    body: JSON.stringify({
                        "move_type": "absolute",
                        "position": this.targetPositionMm,
                        "feed": 1000
                    }),
                })
                .then()
                .catch(function (error) {
                    console.log(error);
                });
        },
        absoluteMoveHandler: function () {
            let x = parseFloat(document.getElementById("input-goto-x").value);
            let y = parseFloat(document.getElementById("input-goto-y").value);
            this.movePlotter({"x": x, "y": y}, "absolute");
        },
        incrementalMoveHandler: function () {
            let x = parseFloat(document.getElementById("input-move-x").value);
            let y = parseFloat(document.getElementById("input-move-y").value);
            this.movePlotter({"x": x, "y": y}, "incremental");
        },
        setPlotterZeroPoint: function () {
            fetch(this.api + this.endpoints.setzero,
                {
                    method: "post",
                    // headers: new Headers({"csrf-token": thisApp.csrfToken}),
                    body: JSON.stringify({
                        "x_flag": true,
                        "y_flag": true,
                        "z_flag": true
                    })
                })
                .then()
                .catch(function(error) {
                    console.log(error);
                });
        },
        imageFetch: function () {
            return fetch(this.api + this.endpoints.image);
        },
        loopFetch: function () {
            this.imageFetch()
                .then(function (response) {
                    let headers = response.headers;
                    thisApp.plotterState = headers.get("Plotter-State");
                    thisApp.plotterPosition = JSON.parse(headers.get("Plotter-Position"));
                    return response.blob();
                })
                .then(function (imageBlob) {
                    // console.log("Updating image.");

                    // Draw on canvas with buffering.
                    let imageUrl = URL.createObjectURL(imageBlob);
                    let image = new Image();

                    canvas = document.getElementById("plotter-canvas");
                    ctx = canvas.getContext("2d");

                    image.onload = function () {

                        // console.log(image.width + ", " + image.height + " | " + canvas.width + ", " + canvas.height);

                        let canvasBuffer = document.createElement("canvas");
                        let contextBuffer = canvasBuffer.getContext("2d");

                        // Set canvas size.
                        canvas.width = image.width;
                        canvas.height = image.height;
                        canvasBuffer.width = image.width;
                        canvasBuffer.height = image.height;
                        thisApp.imageWidth = image.width;
                        thisApp.imageHeight = image.height;

                        // Draw image.
                        contextBuffer.drawImage(image, 0, 0, image.width, image.height,
                            0, 0, canvas.width, canvas.height);
                        // Draw targeting point.
                        thisApp.drawTargetPoint(contextBuffer);

                        ctx.drawImage(canvasBuffer, 0, 0);
                    };

                    image.src = imageUrl;

                    setTimeout(thisApp.loopFetch, 500);
                })
                .catch(function (error) {
                    console.log(error);
                    setTimeout(thisApp.loopFetch, 1000);
                });
        },
    },
    mounted() {

        // Save this pointer.
        thisApp = this;

        // Set up click event for canvas.
        let plotterCanvas = document.getElementById("plotter-canvas");
        let ctx = plotterCanvas.getContext("2d");

        plotterCanvas.addEventListener('click', event => {

            // Get metadata.
            thisApp.getMetadata();

            let bound = plotterCanvas.getBoundingClientRect();

            let x = event.clientX - bound.left - plotterCanvas.clientLeft;
            let y = event.clientY - bound.top - plotterCanvas.clientTop;

            // Set target in pixels.
            thisApp.targetPoint.x = x;
            thisApp.targetPoint.y = y;

            // Convert target in mm.
            thisApp.targetPositionMm = this.convertToMm(x, y);

            // Send command.
            thisApp.movePlotter(thisApp.targetPositionMm, "absolute");

            // Draw target point.
            thisApp.drawTargetPoint(ctx);
        });

        // get csrf token.
        this.csrfToken = Cookies.get('csrftoken');
        console.log(this.csrfToken);

        // Get metadata.
        this.getMetadata();

        // Start fetch plotter status.
        this.loopFetch();
    }
});
