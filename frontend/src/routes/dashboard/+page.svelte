<script>
    import { supabase } from "$lib/subabaseClient";
    import { onMount, onDestroy } from "svelte";
    import Icon from "@iconify/svelte";

    // authentication / session
    let user = null;
    let loading = true;
    let authToken = null;

    onMount(async () => {
        const { data: sessionData } = await supabase.auth.getSession();
        const session = sessionData.session;
        user = session?.user;

        if (!user) {
            window.location.href = "/login";
            return;
        }

        authToken = session.access_token;
        loading = false;
    });

    onDestroy(() => {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        if (pollInterval) clearInterval(pollInterval);
        // remove audio listeners if any (defensive)
        if (audioElem) {
            audioElem.onloadedmetadata = null;
            audioElem.ontimeupdate = null;
            audioElem.onerror = null;
        }
    });

    async function logout() {
        await supabase.auth.signOut();
        window.location.href = "/login";
    }

    // reactive searchbar state
    let youtubeLinkOrQuery = "";
    let isUrl = false;
    let searchResults = [];
    let videoPreview = null;
    let isSearching = false;
    let searchDebounceTimeout;

    const youtubeRegex =
        /(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([\w-]{11})(?:\S+)?/i;
    const apiUrl = import.meta.env.VITE_API_URL.replace(/\/+$/, ""); // ensure no trailing slash

    $: {
        if (loading || !authToken) "";

        const match = youtubeLinkOrQuery.match(youtubeRegex);
        const isUrlMatch = !!match;

        if (isUrlMatch) {
            isUrl = true;
            searchResults = [];
            fetchVideoDetails(match[1]);
        } else {
            isUrl = false;
            // only clear the preview when typing a query
            videoPreview = null;

            clearTimeout(searchDebounceTimeout);
            if (youtubeLinkOrQuery.length > 3) {
                isSearching = true;
                searchDebounceTimeout = setTimeout(() => {
                    searchYouTube(youtubeLinkOrQuery);
                }, 500);
            } else {
                searchResults = [];
                isSearching = false;
            }
        }
    }

    async function fetchVideoDetails(videoId) {
        if (!authToken) {
            console.error("Token missing for fetchVideoDetails.");
            return;
        }

        try {
            isSearching = true;
            const res = await fetch(
                `${apiUrl}/youtube/details?video_id=${videoId}`,
                {
                    headers: { Authorization: `Bearer ${authToken}` },
                },
            );

            if (!res.ok) {
                videoPreview = null;
                const errorBody = await res.json().catch(() => ({}));
                console.error(`API Error ${res.status}:`, errorBody);
                throw new Error(
                    errorBody.detail || "Could not fetch video details.",
                );
            }

            videoPreview = await res.json();
        } catch (error) {
            console.error(error);
        } finally {
            isSearching = false;
        }
    }

    async function searchYouTube(query) {
        if (!authToken || query.length < 3) {
            console.error("Token missing for searchYouTube.");
            return;
        }

        try {
            const res = await fetch(
                `${apiUrl}/youtube/search?query=${encodeURIComponent(query)}`,
                {
                    headers: { Authorization: `Bearer ${authToken}` },
                },
            );

            if (!res.ok) {
                searchResults = [];
                const errorBody = await res.json().catch(() => ({}));
                console.error(`API Error ${res.status}:`, errorBody);
                throw new Error(
                    errorBody.detail || "Could not perform search.",
                );
            }

            const data = await res.json();
            searchResults = data.results || [];
        } catch (error) {
            console.error(error);
        } finally {
            isSearching = false;
        }
    }

    function selectSearchResult(video) {
        youtubeLinkOrQuery = `https://www.youtube.com/watch?v=${video.id}`;
        searchResults = [];
    }

    // API logic / progress / results
    let analysisRunning = false;
    let analysisError = null;
    // notes will be an array of interval objects: { start, end, time, freq, note, left, width }
    let notes = [];
    let vocalsUrl = null;
    let audioElem = null;
    let duration = 0;
    let taskId = null;
    let progress = null;
    let eventSource = null;
    let pollInterval = null;

    let activeIntervalIndex = -1; // which interval is currently playing
    let playUntilEnd = null; // when set, audio should stop when reaching this time
    const DEFAULT_MIN_DURATION = 0.1; // seconds when end missing
    const MIN_WIDTH_PERCENT = 0.2; 
    const progressSteps = ["downloading", "separating", "finalizing", "done"];

    function formatTime(seconds) {
        if (seconds == null || isNaN(Number(seconds))) return "0:00";
        const s = Math.floor(Number(seconds));
        const m = Math.floor(s / 60);
        const sec = (s % 60).toString().padStart(2, "0");
        return `${m}:${sec}`;
    }

    function progressPercentage(step) {
        const index = progressSteps.indexOf(step);
        if (index === -1) return 0;
        return Math.round((index / (progressSteps.length - 1)) * 100);
    }

    // --- NEW: normalize backend intervals into guaranteed numeric start/end/time/freq/note
    // Called inside fetchResult right after notes = data.notes || []
    function normalizeIntervals(rawNotes) {
        if (!Array.isArray(rawNotes)) return [];
        const out = [];
        for (const raw of rawNotes) {
            const rawStart = raw.start ?? raw.time;
            if (rawStart == null) continue;
            const start = Number(rawStart);
            if (Number.isNaN(start)) continue;
            let end =
                raw.end != null
                    ? Number(raw.end)
                    : start + DEFAULT_MIN_DURATION;
            if (Number.isNaN(end)) end = start + DEFAULT_MIN_DURATION;
            if (end <= start) end = start + DEFAULT_MIN_DURATION;
            out.push({
                start,
                end,
                time: start,
                freq: raw.freq != null ? Number(raw.freq) : null,
                note: raw.note ?? "",
            });
        }
        out.sort((a, b) => a.start - b.start);
        return out;
    }

    // --- NEW: compute left/width percentages for each interval (call when duration available)
    function computeGeometry(intervals, audioDuration) {
        if (!audioDuration || audioDuration <= 0) {
            // clear geometry if no duration
            intervals.forEach((i) => {
                i.left = 0;
                i.width = 0;
            });
            return intervals;
        }
        return intervals.map((i) => {
            // clamp times to audio duration
            const s = Math.max(0, Math.min(i.start, audioDuration));
            const e = Math.max(0, Math.min(i.end, audioDuration));
            const rawWidth = ((e - s) / audioDuration) * 100;
            const left = (s / audioDuration) * 100;
            const width = Math.max(rawWidth, MIN_WIDTH_PERCENT); // enforce min vis width
            return { ...i, start: s, end: e, time: s, left, width };
        });
    }

    // --- NEW: audio timeupdate handler to highlight active interval and handle play-until-end
    let lastTimeUpdate = 0;
    function handleTimeUpdate(e) {
        if (!audioElem) return;
        const now = audioElem.currentTime;
        // throttle to ~100ms
        if (performance.now() - lastTimeUpdate < 90) return;
        lastTimeUpdate = performance.now();

        // find active interval
        let found = -1;
        for (let idx = 0; idx < notes.length; idx++) {
            const iv = notes[idx];
            if (now >= iv.start && now < iv.end) {
                found = idx;
                break;
            }
        }
        activeIntervalIndex = found;

        // stop if requested
        if (playUntilEnd != null && now >= playUntilEnd) {
            audioElem.pause();
            playUntilEnd = null;
        }
    }

    // --- NEW: when audio's metadata loads, set duration and compute geometry
    function handleAudioLoadedMetadata() {
        if (!audioElem) return;
        duration = audioElem.duration || 0;
        // compute geometry now that duration known
        notes = computeGeometry(notes, duration);
        // attach timeupdate listener (ensure idempotent)
        audioElem.ontimeupdate = handleTimeUpdate;
        audioElem.onerror = handleAudioError;
        console.log("audio duration:", duration, "intervals:", notes.length);
    }

    function handleAudioError(e) {
        console.error("Audio element error:", e);
    }

    // play and optionally stop at interval end
    function playInterval(idx, stopAtEnd = true) {
        const iv = notes[idx];
        if (!iv || !audioElem) return;
        audioElem.currentTime = iv.start;
        audioElem.play();
        if (stopAtEnd) playUntilEnd = iv.end;
    }

    // legacy playAt uses the same mechanism but doesn't set playUntilEnd
    function playAt(timeSeconds) {
        if (!audioElem) return;
        const t = Math.max(0, Math.min(timeSeconds, duration || timeSeconds));
        audioElem.currentTime = t;
        playUntilEnd = null;
        audioElem.play();
    }

    // --- UPDATED fetchResult: normalize notes and compute absolute vocals URL
    async function fetchResult(taskId) {
        try {
            const res = await fetch(`${apiUrl}/audio/result/${taskId}`, {
                headers: { Authorization: `Bearer ${authToken}` },
            });
            if (res.status === 202) {
                return null;
            }
            if (!res.ok) {
                console.error("Failed to fetch result", await res.text());
                return null;
            }
            const data = await res.json();
            // normalize intervals (backend now returns start/end)
            const raw = data.notes || [];
            const normalized = normalizeIntervals(raw);
            // store normalized intervals in notes but WITHOUT geometry until duration known
            notes = normalized;

            // IMPORTANT: make vocalsUrl absolute (point to backend), because backend returns "/files/..."
            let returned = data.vocals_url || null;
            if (returned) {
                if (/^https?:\/\//.test(returned)) {
                    vocalsUrl = returned;
                } else {
                    vocalsUrl = `${apiUrl}${returned.startsWith("/") ? "" : "/"}${returned}`;
                }
            } else {
                vocalsUrl = null;
            }

            // reset duration so geometry will be recomputed on next loadedmetadata
            duration = 0;
            // clear active and playUntilEnd
            activeIntervalIndex = -1;
            playUntilEnd = null;

            console.log(
                "fetchResult: vocalsUrl =",
                vocalsUrl,
                "normalized intervals:",
                notes.length,
            );
            return data;
        } catch (err) {
            console.error(err);
            return null;
        }
    }

    // When user submits analysis (unchanged except it uses the updated fetchResult)
    async function startAnalysis(e) {
        e.preventDefault();
        analysisError = null;
        analysisRunning = true;

        const selectedPreview = videoPreview; // capture before clearing
        videoPreview = null; // hide preview visually

        if (loading || !authToken) {
            analysisError = "Authentication not ready. Please wait.";
            analysisRunning = false;
            return;
        }

        let urlToSend;
        if (selectedPreview) {
            urlToSend = `https://www.youtube.com/watch?v=${selectedPreview.id}`;
        } else if (youtubeLinkOrQuery) {
            urlToSend = youtubeLinkOrQuery;
        } else {
            console.log("No URL provided");
            analysisRunning = false;
            return;
        }

        try {
            isSearching = true;
            const res = await fetch(`${apiUrl}/audio/process`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${authToken}`,
                    apikey: import.meta.env.VITE_SUPABASE_ANON_KEY,
                },
                body: JSON.stringify({ url: urlToSend }),
            });

            if (!res.ok) {
                const errorBody = await res.json().catch(() => ({}));
                analysisError = errorBody.detail || "Unknown API error.";
                throw new Error(analysisError);
            }

            const data = await res.json();
            taskId = data.task_id;
            progress = "downloading";

            if (eventSource) {
                eventSource.close();
            }

            // Subscribe to SSE progress
            eventSource = new EventSource(`${apiUrl}/audio/progress/${taskId}`);

            eventSource.onmessage = async (event) => {
                progress = event.data;

                if (progress === "done") {
                    // when SSE reports done, fetch the final result
                    if (eventSource) {
                        eventSource.close();
                    }
                    // attempt fetch once immediately; if not ready poll until available
                    const got = await fetchResult(taskId);
                    if (!got) {
                        startResultPoll(taskId);
                    } else {
                        analysisRunning = false;
                    }
                }
            };

            eventSource.onerror = () => {
                console.error("SSE connection lost");
                if (eventSource) {
                    eventSource.close();
                }
                // try to poll results (in case SSE failed but processing completed)
                startResultPoll(taskId);
                analysisRunning = false;
            };
        } catch (error) {
            analysisError =
                analysisError || "Could not connect to the API server.";
            console.error(error);
            analysisRunning = false;
        } finally {
            isSearching = false;
        }
    }

    // Polling fallback: polls /audio/result every 1s until result available or timeout
    function startResultPoll(taskId, timeoutMs = 30000) {
        let elapsed = 0;
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(async () => {
            elapsed += 1000;
            const got = await fetchResult(taskId);
            if (got) {
                clearInterval(pollInterval);
                pollInterval = null;
                analysisRunning = false;
            } else if (elapsed >= timeoutMs) {
                clearInterval(pollInterval);
                pollInterval = null;
                analysisRunning = false;
                analysisError = "Timed out waiting for results.";
            }
        }, 1000);
    }
</script>

<div class="flex flex-col flex-grow gap-6">
    <h1 class="text-center text-6xl text-capitalize text-fuchsia-400 font-bold">
        Paste Your Link
    </h1>

    {#if loading}
        <div class="flex items-center justify-center p-8">
            <Icon
                icon="mdi:loading"
                class="animate-spin w-10 h-10 text-fuchsia-400"
            />
            <span class="ml-3 text-lg text-gray-600"
                >Loading authentication...</span
            >
        </div>
    {:else}
        <form
            on:submit={startAnalysis}
            class="flex items-start w-1/2 max-w-3xl mx-auto space-x-2"
        >
            <label for="simple-search" class="sr-only">Search</label>

            <div class="relative w-full">
                <div
                    class="absolute inset-y-0 start-0 flex items-center justify-center w-14 pointer-events-none"
                >
                    <Icon
                        icon="material-symbols:link-rounded"
                        class="w-8 h-8 text-fuchsia-400"
                    />
                </div>

                <input
                    type="text"
                    id="simple-search"
                    bind:value={youtubeLinkOrQuery}
                    class="py-2.5 border border-gray-400 rounded ps-[3.5rem] text-heading text-sm focus:ring-fuchsia-400 focus:border-fuchsia-400 block w-full placeholder:text-body"
                    placeholder="Add Youtube Video URL or Search..."
                    required
                    disabled={!authToken}
                />

                <div
                    class="absolute z-10 w-full mt-2 bg-white rounded-xl shadow-xl overflow-hidden"
                >
                    {#if isSearching && !videoPreview && searchResults.length === 0}
                        <div
                            class="p-3 flex items-center justify-center text-gray-500 text-sm"
                        >
                            <Icon
                                icon="mdi:loading"
                                class="animate-spin w-5 h-5 mr-2"
                            />
                            Processing...
                        </div>
                    {/if}

                    {#if !analysisRunning && videoPreview && isUrl}
                        <div
                            class="flex flex-col p-3 space-y-1 bg-fuchsia-50 border-t-4 border-fuchsia-600"
                        >
                            <div class="flex gap-2">
                                <div class="img-wrapper">
                                    <img
                                        class="h-auto max-w-3xs rounded"
                                        src={videoPreview.thumbnail}
                                        alt="video thumbnail"
                                    />
                                </div>
                                <div class="preview-info">
                                    <h2 class="font-bold text-left text-xl">
                                        {videoPreview.title}
                                    </h2>
                                    <p
                                        class="font-sm font-light text-fuchsia-400"
                                    >
                                        {videoPreview.channelTitle}
                                    </p>
                                    <p
                                        class="text-sm text-gray-400 mb-2 line-clamp-3 overflow-hidden"
                                    >
                                        {videoPreview.description}
                                    </p>
                                </div>
                            </div>

                            <!-- svelte-ignore a11y_media_has_caption -->
                            <video
                                class="h-80 w-full self-center rounded-lg"
                                controls
                            >
                                <source
                                    src={videoPreview.embedUrl}
                                    type="video/mp4"
                                />
                                Your browser does not support the video tag.
                            </video>
                        </div>
                    {/if}

                    {#if searchResults.length > 0 && !isUrl}
                        <ul
                            class="divide-y divide-gray-100 max-h-80 overflow-y-auto"
                        >
                            {#each searchResults as result}
                                <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
                                <li
                                    on:click={() => selectSearchResult(result)}
                                    on:keypress={() =>
                                        selectSearchResult(result)}
                                    class="flex items-center p-3 space-x-3 cursor-pointer hover:bg-gray-100 transition"
                                    role="button"
                                    tabindex="0"
                                >
                                    <img
                                        src={result.thumbnail}
                                        alt="Thumbnail"
                                        class="w-12 h-8 object-cover rounded"
                                    />
                                    <span
                                        class="text-sm text-gray-700 truncate flex-1"
                                        >{result.title}</span
                                    >
                                </li>
                            {/each}
                        </ul>
                    {/if}

                    {#if progress}
                        <div class="progress-wrapper p-2">
                            {#if progress !== "done"}
                                <div class="flex justify-start m-2">
                                    <span
                                        class="text-sm font-medium text-semibold capitalize"
                                        >{progress}...</span
                                    >
                                </div>
                                <div
                                    class="w-full bg-gray-200 rounded-full h-4"
                                    style="overflow:hidden;"
                                >
                                    <div
                                        class="glass-progress-bar h-4 flex items-center justify-center rounded-full text-xs font-medium text-white text-center p-0.5 leading-none relative"
                                        style="width: {Math.max(
                                            progressPercentage(progress),
                                            6,
                                        )}%;"
                                    >
                                        {progressPercentage(progress)}%
                                        <span class="shine"></span>
                                    </div>
                                </div>
                            {/if}

                            {#if progress === "done"}
                                <p class="text-green-600 mt-2 font-semibold">
                                    Processing complete!
                                </p>
                            {/if}
                        </div>
                    {/if}
                </div>
            </div>

            <button
                type="submit"
                class="inline-flex items-center justify-center shrink-0 text-white bg-fuchsia-400 hover:bg-fuchsia-500 focus:ring-4 focus:ring-fuchsia-300 shadow-xs rounded w-10 h-10 focus:outline-none cursor-pointer transition disabled:bg-gray-400"
                disabled={isSearching || analysisRunning || !authToken}
            >
                <Icon icon="material-symbols:search-rounded" class="w-6 h-6" />
            </button>
        </form>

        {#if analysisError}
            <div
                class="w-1/2 max-w-3xl mx-auto p-3 bg-red-100 border border-red-400 text-red-700 rounded-lg"
                role="alert"
            >
                <p class="font-bold">Analysis Failed</p>
                <p class="text-sm">{analysisError}</p>
                <p class="text-xs mt-1">
                    <span class="font-semibold">Debug Tip:</span> Check your FastAPI
                    console for the exact Supabase error message.
                </p>
            </div>
        {/if}

        {#if vocalsUrl}
            <div
                class="mt-6 w-1/2 max-w-3xl mx-auto bg-white rounded shadow p-4"
            >
                <h3 class="font-semibold mb-2">Vocals</h3>
                <audio
                    bind:this={audioElem}
                    controls
                    src={vocalsUrl}
                    class="w-full"
                    on:loadedmetadata={handleAudioLoadedMetadata}
                    on:error={handleAudioError}
                ></audio>

                {#if notes && notes.length > 0}
                    <div class="mt-4">
                        <h4 class="text-sm font-medium mb-2">
                            Detected notes timeline
                        </h4>

                        <!-- Timeline bar -->
                        <div
                            class="relative w-full h-12 bg-gray-100 rounded overflow-visible"
                            style="padding: 8px;"
                        >
                            <!-- waveform placeholder / background bar -->
                            <div
                                class="absolute left-2 right-2 top-1 bottom-1 bg-white rounded shadow-sm"
                            ></div>

                            <!-- intervals rendered as positioned blocks -->
                            {#each notes as note, i}
                                <button
                                    class="timeline-interval"
                                    on:click={() => playInterval(i, true)}
                                    role="button"
                                    tabindex="0"
                                    aria-label={`Play ${note.note} from ${formatTime(note.start)} to ${formatTime(note.end)}`}
                                    title={`${note.note} — ${formatTime(note.start)} → ${formatTime(note.end)}`}
                                    style="left: {note.left}%; width: {note.width}%;"
                                >
                                    <span class="interval-label"
                                        >{note.note}</span
                                    >
                                </button>
                            {/each}

                            <!-- active highlight overlay (optional visual) -->
                            {#if activeIntervalIndex >= 0}
                                <!-- nothing extra needed, CSS .active handled below -- we toggle via class binding if desired -->
                            {/if}
                        </div>

                        <!-- compact list under timeline -->
                        <ul class="mt-3 divide-y">
                            {#each notes as note, i}
                                <li
                                    class="py-2 flex items-center justify-between"
                                >
                                    <div>
                                        <div class="text-sm font-medium">
                                            {note.note}
                                        </div>
                                        <div class="text-xs text-gray-500">
                                            {formatTime(note.start)} — {formatTime(
                                                note.end,
                                            )} • {note.freq
                                                ? note.freq.toFixed(1)
                                                : "-"} Hz
                                        </div>
                                    </div>
                                    <div>
                                        <button
                                            class="px-2 py-1 bg-fuchsia-400 text-white rounded"
                                            on:click={() =>
                                                playInterval(i, true)}
                                            >▶</button
                                        >
                                    </div>
                                </li>
                            {/each}
                        </ul>
                    </div>
                {:else}
                    <p class="text-sm text-gray-500 mt-3">No notes detected.</p>
                {/if}
            </div>
        {/if}
    {/if}
</div>

<style>
    .glass-progress-bar {
        position: relative;
        background: linear-gradient(90deg, #e879f9 80%, #e879f9 100%);
        overflow: hidden;
    }
    .glass-progress-bar .shine {
        position: absolute;
        top: 0;
        left: -100%;
        width: 50%;
        height: 100%;
        clip-path: polygon(20% 0, 100% 0, 80% 100%, 0% 100%);
        pointer-events: none;
        background: linear-gradient(
            90deg,
            rgba(255, 255, 255, 0.5) 0%,
            rgba(255, 255, 255, 0.45) 100%
        );
        animation: shine-move 1s infinite linear;
    }
    @keyframes shine-move {
        0% {
            left: -100%;
        }
        100% {
            left: 100%;
        }
    }

    /* Timeline interval styles */
    .timeline-interval {
        position: absolute;
        top: 50%;
        transform: translateY(-50%);
        height: 48%; /* visually fit inside bar padding */
        background: rgba(232, 121, 249, 0.95); /* fuchsia-400 */
        border-radius: 6px;
        color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0 6px;
        font-size: 10px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 6px; /* ensure visible even for tiny intervals */
        border: 1px solid rgba(0, 0, 0, 0.08);
        cursor: pointer;
    }
    .timeline-interval:focus {
        outline: 2px solid rgba(232, 121, 249, 0.6);
    }
    .interval-label {
        pointer-events: none;
        font-weight: 600;
    }

    /* small-screen adjustments */
    @media (max-width: 640px) {
        .glass-progress-bar {
            font-size: 10px;
        }
    }
</style>
