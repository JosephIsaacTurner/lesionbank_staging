// static/js/papayaOverlayManager.js
// Encapsulate the code to avoid polluting the global namespace
(function() {
    const PapayaOverlayManager = {
        params: window.overlayParams || {
            "luts": [
                {
                    "name": "Lesion",
                    "alpha": 0.75
                },
                {
                    "name": "Positive Connectivity",
                    "alpha": 0.75
                },
                {
                    "name": "Negative Connectivity",
                    "alpha": 0.75
                }
            ]
        },

        init: function() {
            this.viewer = papayaContainers[0]?.viewer;
            if (!this.viewer) {
                console.error('Papaya viewer not found.');
                return;
            }
            console.log('Papaya viewer initialized:', this.viewer);

            // Attach event listeners to all overlay toggle elements via event delegation
            this.attachToggleListeners();
            this.initSliceUpdateListener();
        },

        attachToggleListeners: function() {
            // Use event delegation: attach a single listener to the document
            document.addEventListener('click', (event) => {
                const element = event.target.closest('[data-toggle-overlay]');
                if (element) {
                    event.preventDefault();
                    const link = element.getAttribute('data-overlay-url');
                    this.toggleOverlay(link, element);
                }
            });
        },

        toggleOverlay: function(link, element) {
            if (!link) {
                console.warn('No link provided for overlay toggle.');
                return;
            }

            const key = this.getOverlayKey(link);
            let overlayParams = this.params[key];

            console.log(`toggleOverlay called with link: ${link}, key: ${key}`);

            if (!overlayParams) {
                console.log(`No overlay parameters found for ${key}.`);
                // Assign default parameters based on file type
                const lowerKey = key.toLowerCase();
                if (lowerKey.includes('roi') && (lowerKey.endsWith('.nii') || lowerKey.endsWith('.nii.gz'))) {
                    console.log(`Assigning ROI parameters for ${key}.`);
                    overlayParams = { lut: "Lesion", alpha: 0.5 };
                } 
                else if (lowerKey.includes('conn') && (lowerKey.endsWith('.nii') || lowerKey.endsWith('.nii.gz'))) {
                    overlayParams = {
                        lut: "Positive Connectivity",
                        negative_lut: "Negative Connectivity",
                        alpha: 0.75,
                        parametric: true,
                        symmetric: true,
                        min: 5,
                        max: 45
                    };
                }
                else if (lowerKey.includes('percent_overlap') && (lowerKey.endsWith('.nii') || lowerKey.endsWith('.nii.gz'))) {
                    overlayParams = {
                        lut: "Positive Connectivity",
                        negative_lut: "Negative Connectivity",
                        alpha: 0.75,
                        parametric: true,
                        symmetric: true,
                        min: 25,
                        max: 80
                    };
                }
                else {
                    // Assign a generic default
                    console.log(`Assigning default parameters for ${key}.`);
                    overlayParams = { lut: "Default", alpha: 1.0 };
                }

                this.params[key] = overlayParams; // Assign to params for future use

                // Assign params to the viewer's container
                if (!this.viewer.container.params) {
                    this.viewer.container.params = {};
                }
                this.viewer.container.params[key] = overlayParams; // Assign to Papaya's params
            }

            console.log(`Overlay parameters for ${key}:`, overlayParams);
            console.log('Viewer container params before loading overlay:', this.viewer.container.params);

            // Proceed if overlayParams are available
            if (overlayParams) {
                console.log(`Toggling overlay: ${key}`);
                let viewer = this.viewer;
                let overlays = viewer.screenVolumes;
                let overlay_list = overlays.map(overlay => overlay.volume.urls[0]);

                console.log('Current overlay list:', overlay_list);

                if (overlay_list.includes(link)) {
                    // Overlay is already loaded; toggle it off/on
                    let i = overlay_list.indexOf(link);
                    console.log(`Overlay already loaded at index ${i}. Toggling visibility.`);
                    viewer.toggleOverlay(i);

                    // Apply LUT after toggling
                    let screenVolume = viewer.screenVolumes[i];
                    this.applyLutToVolume(screenVolume, overlayParams);
                } else {
                    // Overlay not loaded; load it
                    console.log(`Overlay not loaded. Loading overlay from link: ${link}`);
                    if (overlayParams.parametric === true) {
                        papaya.viewer.Viewer.MAX_OVERLAYS += 2;
                    } else {
                        papaya.viewer.Viewer.MAX_OVERLAYS += 1;
                    }

                    // Backup the original initializeOverlay method
                    let originalInitializeOverlay = viewer.initializeOverlay.bind(viewer);

                    // Capture 'this' and overlayParams for use inside initializeOverlay
                    const self = this;
                    const currentOverlayParams = overlayParams;

                    // Override the initializeOverlay method
                    viewer.initializeOverlay = function() {
                        console.log('initializeOverlay called.');
                        // Call the original method to ensure normal operation
                        originalInitializeOverlay();

                        console.log('After original initializeOverlay.');
                        console.log('Viewer container params in initializeOverlay:', viewer.container.params);

                        // Find all screen volumes associated with the new overlay
                        let matchingScreenVolumes = viewer.screenVolumes.filter(function(sv) {
                            return sv.volume === viewer.loadingVolume;
                        });

                        console.log('Matching screen volumes:', matchingScreenVolumes);

                        if (matchingScreenVolumes.length > 0) {
                            console.log('Applying LUTs to matching screen volumes.');
                            matchingScreenVolumes.forEach(function(screenVolume) {
                                self.applyLutToVolume(screenVolume, currentOverlayParams);
                            });
                        } else {
                            console.warn('No matching screen volumes found in initializeOverlay.');
                        }

                        // Restore the original initializeOverlay method
                        viewer.initializeOverlay = originalInitializeOverlay;
                    };

                    // Assign params to the viewer's container
                    if (!this.viewer.container.params) {
                        this.viewer.container.params = {};
                    }
                    this.viewer.container.params[key] = overlayParams; // Assign to Papaya's params

                    console.log('Viewer container params before loadOverlay:', this.viewer.container.params);

                    // Load the overlay
                    viewer.loadOverlay([link], true, false, false);
                }

                // Toggle the icon classes for visual feedback
                if (element instanceof HTMLElement) {
                    element.classList.toggle("bi-square-fill");
                    element.classList.toggle("bi-square");
                }
            }
        },

        applyLutToVolume: function(screenVolume, overlayParams) {
            console.log('Applying LUT to volume:', screenVolume);
            console.log('Overlay parameters:', overlayParams);

            let lutName;
            if (screenVolume.negative) {
                // Negative screen volume
                lutName = overlayParams.negative_lut;
                console.log('Applying negative LUT to negative screen volume:', lutName);
            } else {
                // Positive screen volume
                lutName = overlayParams.lut;
                console.log('Applying positive LUT to positive screen volume:', lutName);
            }

            let lut = this.getLutByName(lutName);
            if (lut) {
                console.log(`Applying LUT "${lut.name}" to volume.`);
                if (typeof screenVolume.changeColorTable === 'function') {
                    // Use Papaya's changeColorTable method
                    screenVolume.alpha = lut.alpha || overlayParams.alpha || 0.75;
                    screenVolume.changeColorTable(this.viewer, lut.name);
                    console.log(`LUT "${lut.name}" applied successfully.`);
                } else {
                    console.warn(`changeColorTable method not found on screenVolume.`);
                }
            } else {
                console.warn(`LUT "${lutName}" not found. Applying default LUT.`);
                // Optionally, apply a default LUT
                let defaultLut = this.getLutByName("Grayscale"); // Ensure "Grayscale" exists
                if (defaultLut) {
                    screenVolume.changeColorTable(this.viewer, defaultLut.name);
                    console.log(`Default LUT "${defaultLut.name}" applied.`);
                }
            }
        },

        getOverlayKey: function(link) {
            console.log('Extracting overlay key from link:', link);
            return link.split('/').pop();
        },

        getLutByName: function(name) {
            if (!this.params.luts) {
                console.warn('No LUTs defined in overlayParams.');
                return null;
            }
            for (let i = 0; i < this.params.luts.length; i += 1) {
                if (this.params.luts[i].name === name) {
                    console.log(`Found LUT "${name}".`);
                    return this.params.luts[i];
                }
            }
            console.warn(`LUT "${name}" not found in params.luts.`);
            return null;
        },
        
        initSliceUpdateListener: function() {
            let viewer = this.viewer;

            if (!viewer) {
                console.error('Viewer instance not found for slice update listener.');
                return;
            }

            /**
             * Helper function to round a number to the nearest even integer.
             * @param {number} num - The number to round.
             * @returns {number} - The nearest even integer.
             */
            function roundToNearestEven(num) {
                const rounded = Math.round(num);
                if (rounded % 2 === 0) {
                    return rounded;
                } else {
                    const lowerEven = rounded - 1;
                    const upperEven = rounded + 1;
                    // Choose the even integer that is closer to the original number
                    return (Math.abs(num - lowerEven) < Math.abs(num - upperEven)) ? lowerEven : upperEven;
                }
            }

            /**
             * Debounce function to limit the rate at which a function can fire.
             * @param {Function} func - The function to debounce.
             * @param {number} wait - The number of milliseconds to delay.
             * @returns {Function} - The debounced function.
             */
            function debounce(func, wait) {
                let timeout;
                return function(...args) {
                    const later = () => {
                        clearTimeout(timeout);
                        func.apply(this, args);
                    };
                    clearTimeout(timeout);
                    timeout = setTimeout(later, wait);
                };
            }

            /**
             * Debounced function to update the coordinate form fields.
             * @param {papaya.core.Coordinate} coord_obj - The coordinate object containing x, y, z.
             */
            const updateFormFields = debounce(function(coord_obj) {
                $('#inputX').val(roundToNearestEven(coord_obj.x));
                $('#inputY').val(roundToNearestEven(coord_obj.y));
                $('#inputZ').val(roundToNearestEven(coord_obj.z));
            }, 100); // 100ms debounce delay

            /**
             * Function to override the updateSlice method of a given slice.
             * @param {papaya.viewer.ScreenSlice} slice - The slice object to override.
             */
            function overrideUpdateSlice(slice) {
                if (!slice || typeof slice.updateSlice !== 'function') {
                    console.warn('Invalid slice object. Cannot override updateSlice.');
                    return;
                }

                // Store the original updateSlice method
                const originalUpdateSlice = slice.updateSlice.bind(slice);

                // Override the updateSlice method
                slice.updateSlice = function(sliceNumber, force, worldSpace) {
                    // Call the original updateSlice method
                    originalUpdateSlice(sliceNumber, force, worldSpace);

                    // After updating the slice, retrieve the current coordinates
                    // Assuming viewer.currentCoord is updated accordingly
                    let currentCoord = viewer.currentCoord; // {x, y, z}

                    // Convert image coordinates to world coordinates
                    let coord_obj = new papaya.core.Coordinate();
                    viewer.getWorldCoordinateAtIndex(currentCoord.x, currentCoord.y, currentCoord.z, coord_obj);

                    // Update the form fields with the rounded coordinates
                    updateFormFields(coord_obj);
                };

                console.log(`Overridden updateSlice for slice: ${slice.sliceDirection}`);
            }

            // Override updateSlice for each slice if they exist
            if (viewer.axialSlice) {
                overrideUpdateSlice(viewer.axialSlice);
            }
            if (viewer.coronalSlice) {
                overrideUpdateSlice(viewer.coronalSlice);
            }
            if (viewer.sagittalSlice) {
                overrideUpdateSlice(viewer.sagittalSlice);
            }
            if (viewer.surfaceView) {
                overrideUpdateSlice(viewer.surfaceView);
            }

            console.log('Slice update listener initialized.');
        }
    };

    // Expose PapayaOverlayManager to the global scope if needed
    window.PapayaOverlayManager = PapayaOverlayManager;
})();
