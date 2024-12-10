// Estatic/js/papayaSegmenter.js
(function() {
    const PapayaSegmenter = {
        // Store instance variables
        viewer: null,
        canvas: null,
        papayaPrototype: null,
        lassoList: [],
        worldLassoList: [],
        voxels: [],
        initialized: false,
        isLassoToolActive: false,  // Flag to track lasso tool state
        mousedownHandler: null,
        mousemoveHandler: null,
        mouseupHandler: null,

        init: function() {
            if (this.initialized) {
                console.log('PapayaSegmenter already initialized.');
                return;
            }
            this.initialized = true;

            // Store the viewer reference
            this.viewer = papayaContainers[0]?.viewer;
            if (!this.viewer) {
                console.error('Papaya viewer not found.');
                return null;
            }

            // Wait for canvas to be available
            this.canvas = document.querySelector("canvas");
            if (!this.canvas) {
                console.error('Canvas element not found.');
                return null;
            }

            // Get papaya prototype
            this.papayaPrototype = papaya?.viewer?.Viewer?.prototype;
            if (!this.papayaPrototype) {
                console.error('Papaya prototype not found.');
                return null;
            }

            // Override the drawViewer method
            this.viewer.drawViewer = this.drawViewer.bind(this);

            // Attach event listeners for buttons
            this.attachEventListeners();

            // Set initial button state
            const toggleButton = document.getElementById("segmentToggleButton");
            if (toggleButton) {
                toggleButton.classList.remove("active");
                toggleButton.classList.remove("btn-success");
                toggleButton.classList.add("btn-primary");
                toggleButton.textContent = "Lasso Tool: OFF";
            }

            console.log('PapayaSegmenter initialized successfully');

            return this;
        },

        attachEventListeners: function() {
            // Ensure the DOM is fully loaded
            const toggleButton = document.getElementById("segmentToggleButton");
            const clearButton = document.getElementById("segmentClearButton");
            const exportButton = document.getElementById("segmentExportButton");
            const analyzeButton = document.getElementById("segmentAnalyze");
            if (toggleButton) {
                toggleButton.addEventListener("click", () => {
                    if (this.isLassoToolActive) {
                        this.disableLassoTool();
                    } else {
                        this.enableLassoTool();
                    }
                });
            } else {
                console.warn('Toggle button with ID "segmentToggleButton" not found.');
            }

            if (clearButton) {
                clearButton.addEventListener("click", () => {
                    this.clearAll();
                    console.log('All lassos cleared.');
                });
            } else {
                console.warn('Clear button with ID "segmentClearButton" not found.');
            }

            if (exportButton) {
                exportButton.addEventListener("click", () => {
                    const voxels = this.getVoxels();
                    if (voxels.length === 0) {
                        alert('No voxels to export. Please create a lasso first.');
                        return;
                    }
                    this.exportAsNIfTI(voxels);
                });
            } else {
                console.warn('Export button with ID "segmentExportButton" not found.');
            }

            if (analyzeButton) {
                analyzeButton.addEventListener("click", () => {
                    const voxels = this.getVoxels();
                    if (voxels.length === 0) {
                        alert('No voxels to analyze. Please create a lasso first.');
                        return;
                    }
                    this.analyzeVoxels(voxels);
                });
            } else {
                console.warn('Analyze button with ID "segmentAnalyze" not found.');
            }

        },

        enableLassoTool: function() {
            if (this.isLassoToolActive) {
                return;
            }
            this.isLassoToolActive = true;

            // Update the toggle button style
            const toggleButton = document.getElementById("segmentToggleButton");
            if (toggleButton) {
                toggleButton.classList.add("active");
                toggleButton.classList.add("btn-success");
                toggleButton.classList.remove("btn-primary");
                toggleButton.textContent = "Lasso Tool: ON";
            }

            let points = [];
            let isDrawing = false;
            let ctx = this.canvas.getContext('2d');

            // Define the event handlers
            this.mousedownHandler = (e) => {
                isDrawing = true;
                points.push({
                    x: e.offsetX,
                    y: e.offsetY,
                });
            };

            this.mousemoveHandler = (e) => {
                if (!isDrawing) return;
                points.push({
                    x: e.offsetX,
                    y: e.offsetY,
                });
                this.drawPath(points, ctx);
            };

            this.mouseupHandler = (e) => {
                if (!isDrawing) return;
                isDrawing = false;
                let path = new Path2D();
                path.moveTo(points[0].x, points[0].y);

                for (let i = 1; i < points.length; i++) {
                    let testPoint = {
                        x: this.viewer.convertScreenToImageCoordinateX(points[i].x, this.viewer.axialSlice),
                        y: this.viewer.convertScreenToImageCoordinateY(points[i].y, this.viewer.axialSlice),
                        z: this.viewer.cursorPosition.z
                    };
                    if (this.viewer.intersectsMainSlice(testPoint)) {
                        path.lineTo(points[i].x, points[i].y);
                    }
                }

                ctx.fillStyle = "rgba(255, 0, 0, 0.5)";
                ctx.fill(path);

                let lassoPoints = points.map(point => [point.x, point.y]);
                this.addToLassoList(lassoPoints);
                points = [];
            };

            // Add event listeners
            this.canvas.addEventListener("mousedown", this.mousedownHandler);
            this.canvas.addEventListener("mousemove", this.mousemoveHandler);
            this.canvas.addEventListener("mouseup", this.mouseupHandler);
        },

        disableLassoTool: function() {
            if (!this.isLassoToolActive) {
                return;
            }
            this.isLassoToolActive = false;

            // Update the toggle button style
            const toggleButton = document.getElementById("segmentToggleButton");
            if (toggleButton) {
                toggleButton.classList.remove("active");
                toggleButton.classList.remove("btn-success");
                toggleButton.classList.add("btn-primary");
                toggleButton.textContent = "Lasso Tool: OFF";
            }

            // Remove event listeners
            this.canvas.removeEventListener("mousedown", this.mousedownHandler);
            this.canvas.removeEventListener("mousemove", this.mousemoveHandler);
            this.canvas.removeEventListener("mouseup", this.mouseupHandler);

            // Reset event handlers
            this.mousedownHandler = null;
            this.mousemoveHandler = null;
            this.mouseupHandler = null;
        },

        drawPath: function(points, ctx) {
            ctx.strokeStyle = 'magenta';
            ctx.beginPath();
            ctx.moveTo(points[0].x, points[0].y);
            for (let i = 1; i < points.length; i++) {
                let testPoint = {
                    x: this.viewer.convertScreenToImageCoordinateX(points[i].x, this.viewer.axialSlice),
                    y: this.viewer.convertScreenToImageCoordinateY(points[i].y, this.viewer.axialSlice),
                    z: this.viewer.cursorPosition.z
                };
                if (this.viewer.intersectsMainSlice(testPoint)) {
                    ctx.lineTo(points[i].x, points[i].y);
                }
            }
            ctx.stroke();
        },

        clearAll: function() {
            this.lassoList = [];
            this.worldLassoList = [];
            this.voxels = [];
            this.viewer.drawViewer();
        },

        addToLassoList: function(lassoPoints) {
            let lasso = [];
            lassoPoints.forEach(point => {
                let cursorPosition = this.viewer.cursorPosition;
                let newPoint = {
                    x: this.viewer.convertScreenToImageCoordinateX(point[0], this.viewer.axialSlice),
                    y: this.viewer.convertScreenToImageCoordinateY(point[1], this.viewer.axialSlice),
                    z: cursorPosition.z
                };
                if (this.viewer.intersectsMainSlice(newPoint)) {
                    if (!lasso.some(existingPoint =>
                        existingPoint.x === newPoint.x &&
                        existingPoint.y === newPoint.y &&
                        existingPoint.z === newPoint.z)) {
                        lasso.push(newPoint);
                    }
                }
            });
            this.lassoList.push(lasso);
        },

        drawViewer: function() {
            let result = this.papayaPrototype.drawViewer.apply(this.viewer, arguments);

            for (let i = 0; i < this.lassoList.length; i++) {
                let screenPoints = [];
                this.lassoList[i].forEach(point => {
                    if (this.viewer.intersectsMainSlice(point)) {
                        let screenCoor = this.viewer.convertCoordinateToScreen(point);
                        screenPoints.push(screenCoor);
                    }
                });

                if (screenPoints.length > 1) {
                    let path = new Path2D();
                    path.moveTo(screenPoints[0].x, screenPoints[0].y);
                    for (let j = 1; j < screenPoints.length; j++) {
                        path.lineTo(screenPoints[j].x, screenPoints[j].y);
                    }
                    let ctx = this.viewer.context;
                    ctx.fillStyle = "rgba(255, 0, 0, 0.5)";
                    ctx.fill(path);
                }
            }

            return result;
        },

        lassoToWorld: function() {
            this.worldLassoList = [];
            this.lassoList.forEach(lasso => {
                let worldLasso = [];
                lasso.forEach(point => {
                    let worldPoint = this.viewer.getWorldCoordinateAtIndex(
                        point.x, point.y, point.z,
                        new papaya.core.Coordinate()
                    );
                    worldLasso.push({
                        x: worldPoint.x,
                        y: worldPoint.y,
                        z: worldPoint.z
                    });
                });
                this.worldLassoList.push(worldLasso);
            });
            return this.worldLassoList;
        },

        pointsInPolygon: function(polygonPoints, width = 1000, height = 1000) {
            let myScope = new paper.PaperScope();
            myScope.setup(new myScope.Size(width, height));
            let path = new myScope.Path();

            polygonPoints.forEach(function(point) {
                path.add(new myScope.Point(point.x, point.y));
            });

            path.closed = true;
            let bounds = path.bounds;
            let insidePoints = [];

            for (let x = bounds.left; x < bounds.right; x++) {
                for (let y = bounds.top; y < bounds.bottom; y++) {
                    let point = new myScope.Point(x, y);
                    if (path.contains(point)) {
                        insidePoints.push({ x: x, y: y });
                    }
                }
            }

            return insidePoints.map(point => ({
                x: point.x,
                y: point.y,
                z: polygonPoints[0].z
            }));
        },

        getVoxels: function() {
            this.lassoToWorld();
            this.voxels = [];

            this.worldLassoList.forEach(sub_list => {
                let point_list = this.pointsInPolygon(sub_list);
                point_list.forEach(inner_point => {
                    if (!this.voxels.some(op =>
                        op.x === inner_point.x &&
                        op.y === inner_point.y &&
                        op.z === inner_point.z)) {
                        this.voxels.push(inner_point);
                    }
                });
            });

            return this.voxels.map(point => [point.x, point.y, point.z, 1]);
        },

        exportAsNIfTI: function(voxels) {
            // Convert voxels to JSON string
            const data = JSON.stringify(voxels);

            // Send the voxels to the endpoint via a POST request
            fetch('/voxel_to_nifti/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',  // Set content type to JSON
                    'Accept': 'application/gzip'         // We expect a gzipped NIfTI file in response
                },
                body: data
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => { throw err; });
                }
                return response.blob();  // Get the response as a blob
            })
            .then(blob => {
                // Create a download link and trigger it
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'segmented_image.nii.gz';
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
            })
            .catch(error => {
                console.error('Error exporting NIfTI:', error);
                alert('An error occurred while exporting the NIfTI file.');
            });
        },

        analyzeVoxels: function(voxels) {
            // Convert voxels to JSON string
            const data = JSON.stringify(voxels);
        
            // Get CSRF token
            const csrftoken = this.getCSRFToken();
        
            // Send the voxels to the endpoint via a POST request
            fetch('/analyze_voxels/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrftoken
                },
                body: data
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => { throw err; });
                }
                return response.json();
            })
            .then(data => {
                // Redirect to progress page with task_id
                window.location.href = `/analyze_progress/?task_id=${data.task_id}`;
            })
            .catch(error => {
                console.error('Error analyzing voxels:', error);
                alert('An error occurred while analyzing the lesion.');
            });
        },
        
        getCSRFToken: function() {
            // Function to get CSRF token from cookies
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, 10) === ('csrftoken=')) {
                        cookieValue = decodeURIComponent(cookie.substring(10));
                        break;
                    }
                }
            }
            return cookieValue;
        }
    };

    // Expose PapayaSegmenter to the global scope
    window.PapayaSegmenter = PapayaSegmenter;
})();