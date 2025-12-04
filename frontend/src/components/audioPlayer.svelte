<script>
    import { onMount, onDestroy, createEventDispatcher } from "svelte";
    import Icon from "@iconify/svelte";
    import { browser } from "$app/environment";

    export let src = "";

    const dispatch = createEventDispatcher();

    let myTrackbar;
    let myAudio;

    let isPlaying = false;
    let currentTime = 0;
    let duration = 0;
    let progressPercentage = 0;

    let isSeeking = false;
    let ignoreNextPause = false;

    function togglePlayPause() {
        if (!myAudio) {
            console.error("No audio element found");
            return;
        }

        console.log(
            "Toggle clicked, current isPlaying:",
            isPlaying,
            "audio.paused:",
            myAudio.paused,
        );

        if (myAudio.paused) {
            console.log("Starting playback");
            myAudio.play().catch((e) => {
                console.error("Playback failed:", e);
            });
        } else {
            console.log("Pausing playback");
            myAudio.pause();
        }
    }

    function handleTimeUpdate() {
        if (!myAudio || isSeeking) return;

        currentTime = myAudio.currentTime;

        if (duration > 0) {
            progressPercentage = (currentTime / duration) * 100;
        }
    }

    function handleLoadedMetadata() {
        if (myAudio) {
            duration = myAudio.duration || 0;
            dispatch("element", { element: myAudio });
            console.log("Audio metadata loaded, duration:", duration);

            if (currentTime > 0 && duration > 0) {
                progressPercentage = (currentTime / duration) * 100;
            }
        }
    }

    // 💡 CRITICAL UPDATE: The corrected seekTo function
    function seekTo(event) {
        if (!myTrackbar || !duration || !myAudio) return;

        event.preventDefault?.();

        ignoreNextPause = true;
        isSeeking = true;

        const rect = myTrackbar.getBoundingClientRect();
        let clientX;

        if (event.type.startsWith("touch")) {
            const touch = event.touches?.[0] || event.changedTouches?.[0];
            if (!touch) return;
            clientX = touch.clientX;
        } else {
            clientX = event.clientX;
        }

        const percent = Math.min(
            Math.max((clientX - rect.left) / rect.width, 0),
            1,
        );

        // Update local state first
        currentTime = percent * duration;
        progressPercentage = percent * 100;

        // 1. Set isSeeking to TRUE (to prevent on:pause from firing)
        const wasPlaying = !myAudio.paused; // Store state before seek

        // 2. Set the audio position
        myAudio.currentTime = currentTime;

        // 3. Only restart playback if it was previously playing.
        if (wasPlaying) {
            myAudio
                .play()
                .then(() => {
                    isPlaying = true;
                })
                .catch((e) => {
                    console.error("Playback failed during seek play:", e);
                    isSeeking = false; // Fail-safe
                });
        }
        // isSeeking will be reset to false by the on:seeked handler
    }

    function formatTime(seconds) {
        if (!seconds || isNaN(seconds) || !isFinite(seconds)) return "0:00";
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = Math.floor(seconds % 60);
        return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
    }

    function updateMeasurements() {
        if (myTrackbar) {
            const rect = myTrackbar.getBoundingClientRect();
            dispatch("measure", { width: rect.width, left: rect.left });
        }
    }

    onMount(() => {
        if (!browser) return;

        const t = setTimeout(() => {
            updateMeasurements();
            if (myAudio && myAudio.readyState >= 1) {
                handleLoadedMetadata();
            }
        }, 100);

        window.addEventListener("resize", updateMeasurements);

        return () => {
            clearTimeout(t);
            window.removeEventListener("resize", updateMeasurements);
        };
    });

    onDestroy(() => {
        if (browser) {
            window.removeEventListener("resize", updateMeasurements);
        }
    });

    // Reset state when src changes
    $: if (src) {
        console.log("Source changed to:", src);
        currentTime = 0;
        isPlaying = false;
        progressPercentage = 0;
        duration = 0;
        isSeeking = false;

        if (browser) {
            setTimeout(() => {
                if (myAudio && myAudio.readyState >= 1) {
                    handleLoadedMetadata();
                }
            }, 100);
        }
    }
</script>

<audio
    bind:this={myAudio}
    {src}
    on:timeupdate={handleTimeUpdate}
    on:loadedmetadata={handleLoadedMetadata}
    on:loadeddata={handleLoadedMetadata}
    on:ended={() => {
        console.log("Audio ended");
        isPlaying = false;
        currentTime = 0;
        progressPercentage = 0;
    }}
    on:play={() => {
        console.log("Audio play event fired");
        isPlaying = true;
    }}
    on:pause={() => {
        if (ignoreNextPause) {
            console.log("Ignoring pause caused by seeking");
            ignoreNextPause = false; // reset
            return;
        }

        if (!isSeeking) {
            console.log("Audio pause event fired (not seeking)");
            isPlaying = false;
        } else {
            console.log("Ignoring pause event during seeking");
        }
    }}
    on:seeked={() => {
        console.log("Seek complete, resetting flags");
        isSeeking = false;
        ignoreNextPause = false; // <-- add this
    }}
    on:error={(e) => {
        console.error("Audio error:", e, myAudio?.error);
        isPlaying = false;
        isSeeking = false;
    }}
    preload="metadata"
>
    Your browser does not support the audio element.
</audio>

<div
    class="audio-player flex items-center justify-between h-16 mt-6 mb-24 select-none"
>
    <button
        class="play-btn cursor-pointer"
        title={isPlaying ? "Pause" : "Play"}
        aria-label={isPlaying ? "Pause audio" : "Play audio"}
        aria-pressed={isPlaying}
        on:click={togglePlayPause}
        type="button"
    >
        <Icon
            icon={isPlaying
                ? "material-symbols:pause-circle-rounded"
                : "material-symbols:play-circle-rounded"}
            class="h-10 w-10 mr-4 text-fuchsia-400"
        />
    </button>

    <div
        class="trackbar-wrapper relative flex-1 flex items-center min-w-0"
    >
        <div
            bind:this={myTrackbar}
            class="trackbar relative w-[99.5%] h-3 bg-gray-200 rounded-lg cursor-pointer"
            on:click={seekTo}
            on:touchstart|preventDefault={seekTo}
        >
            <!-- Progress fill -->
            <div
                class="trackbar-progress absolute h-full bg-gradient-to-r from-fuchsia-400 to-fuchsia-400 rounded-md left-0 top-0 pointer-events-none transition-width duration-100"
                style="width: {progressPercentage}%;"
            ></div>
            <!-- Simple thumb (non-draggable) -->
            <span
                class="trackbar-thumb absolute top-1/2 h-6 w-6 bg-gray-50 border-4 border-gray-400 rounded-full z-20 pointer-events-none"
                style="left: {progressPercentage}%; transform: translate(-50%, -50%);"
                aria-hidden="true"
            ></span>
        </div>

        <div
            class="timeline-slot absolute top-full right-0 w-[99.5%] h-10 pointer-events-none"
        >
            <slot name="timeline" />
        </div>
    </div>

    <div
        class="audio-timestamp-wrapper flex items-center ml-1"
    >
        <span
            class="audio-timestamp inline-block px-4 py-1 bg-gray-200 rounded-full font-semibold text-gray-500 text-sm whitespace-nowrap"
        >
            {formatTime(currentTime)} / {formatTime(duration)}
        </span>
    </div>
</div>

<style>
    .timeline-slot {
        position: absolute;
        left: 0;
        right: 0;
        pointer-events: none;
        display: flex;
        flex-direction: row;
        z-index: 11;
    }

    :global(.timeline-slot > *) {
        pointer-events: auto;
    }
</style>
