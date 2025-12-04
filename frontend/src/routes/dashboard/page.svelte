<script>
    import { supabase } from "$lib/subabaseClient";
    import { onMount, onDestroy } from "svelte";
    import Icon from "@iconify/svelte";
    import AudioPlayer from "../../components/audioPlayer.svelte";

    // reactive auth / UI state
    let user = null;
    let loading = true;
    let authToken = null;

    // search & video preview state
    let youtubeLinkOrQuery = "";
    let isUrl = false;
    let searchResults = [];
    let videoPreview = null;
    let isSearching = false;
    let searchDebounceTimeout;

    const youtubeRegex =
        /(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([\w-]{11})(?:\S+)?/i;
    const apiUrl = import.meta.env.VITE_API_URL.replace(/\/+$/, ""); // ensure no trailing slash

    // analysis / backend state
    let analysisRunning = false;
    let analysisError = null;
    let notes = []; // normalized intervals (start,end,time,freq,note,left,width)
    let vocalsUrl = null;
    let duration = 0;
    let taskId = null;
    let progress = null;
    let eventSource = null;
    let pollInterval = null;
    let audioElem = null; // will be set from AudioPlayer via on:element
    let activeIntervalIndex = -1;
    let playUntilEnd = null;
    const DEFAULT_MIN_DURATION = 0.1;
    const MIN_WIDTH_PERCENT = 0.2;
    const progressSteps = ["downloading", "separating", "finalizing", "done"];

    // --- lifecycle: auth
    onMount(async () => {
        try {
            const { data: sessionData } = await supabase.auth.getSession();
            const session = sessionData.session;
            user = session?.user;

            if (!user) {
                window.location.href = "/login";
                return;
            }

            authToken = session.access_token;
        } catch (err) {
            console.error("Auth error:", err);
            window.location.href = "/login";
            return;
        } finally {
            loading = false;
        }
    });

    onDestroy(() => {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        if (pollInterval) clearInterval(pollInterval);
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

    $: if (youtubeLinkOrQuery && authToken) {
        const match = youtubeLinkOrQuery.match(youtubeRegex);
        const isUrlMatch = !!match;

        if (isUrlMatch) {
            isUrl = true;
            searchResults = [];
            videoPreview = null;
            fetchVideoDetails(match[1]);
        } else {
            isUrl = false;
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

    // --- youtube helpers
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
                const err = await res.json().catch(() => ({}));
                console.error("API error:", err);
                return;
            }

            videoPreview = await res.json();
        } catch (err) {
            console.error("fetchVideoDetails error:", err);
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
            isSearching = true;
            const res = await fetch(
                `${apiUrl}/youtube/search?query=${encodeURIComponent(query)}`,
                {
                    headers: { Authorization: `Bearer ${authToken}` },
                },
            );

            if (!res.ok) {
                searchResults = [];
                const err = await res.json().catch(() => ({}));
                console.error("Search API error:", err);
                return;
            }

            const data = await res.json();
            searchResults = data.results || [];
        } catch (err) {
            console.error("searchYouTube error:", err);
        } finally {
            isSearching = false;
        }
    }

    function selectSearchResult(video) {
        youtubeLinkOrQuery = `https://www.youtube.com/watch?v=${video.id}`;
        searchResults = [];
    }

    // --- normalization + geometry
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

    function computeGeometry(intervals, audioDuration) {
        if (!audioDuration || audioDuration <= 0) {
            intervals.forEach((i) => {
                i.left = 0;
                i.width = 0;
            });
            return intervals;
        }
        return intervals.map((i) => {
            const s = Math.max(0, Math.min(i.start, audioDuration));
            const e = Math.max(0, Math.min(i.end, audioDuration));
            const rawWidth = ((e - s) / audioDuration) * 100;
            const left = (s / audioDuration) * 100;
            const width = Math.max(rawWidth, MIN_WIDTH_PERCENT);
            return { ...i, start: s, end: e, time: s, left, width };
        });
    }

    // --- audio event handlers + playback helpers
    let lastTimeUpdate = 0;
    function handleTimeUpdate() {
        if (!audioElem) return;
        const now = audioElem.currentTime;
        if (performance.now() - lastTimeUpdate < 90) return;
        lastTimeUpdate = performance.now();

        let found = -1;
        for (let idx = 0; idx < notes.length; idx++) {
            const iv = notes[idx];
            if (now >= iv.start && now < iv.end) {
                found = idx;
                break;
            }
        }
        activeIntervalIndex = found;

        if (playUntilEnd != null && now >= playUntilEnd) {
            audioElem.pause();
            playUntilEnd = null;
        }
    }

    function handleAudioLoadedMetadata() {
        if (!audioElem) return;
        duration = audioElem.duration || 0;
        notes = computeGeometry(notes, duration);
        audioElem.ontimeupdate = handleTimeUpdate;
        audioElem.onerror = handleAudioError;
        console.log("audio duration:", duration, "intervals:", notes.length);
    }

    function handleAudioError(e) {
        console.error("Audio element error:", e);
    }

    function playInterval(idx, stopAtEnd = true) {
        const iv = notes[idx];
        if (!iv || !audioElem) return;
        audioElem.currentTime = iv.start;
        audioElem.play();
        if (stopAtEnd) playUntilEnd = iv.end;
    }

    function playAt(timeSeconds) {
        if (!audioElem) return;
        const t = Math.max(0, Math.min(timeSeconds, duration || timeSeconds));
        audioElem.currentTime = t;
        playUntilEnd = null;
        audioElem.play();
    }

    // --- result fetching and SSE orchestration
    async function fetchResult(taskIdParam) {
        try {
            const res = await fetch(`${apiUrl}/audio/result/${taskIdParam}`, {
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

            const raw = data.notes || [];
            const normalized = normalizeIntervals(raw);
            // store normalized intervals (geometry computed later on loadedmetadata)
            notes = normalized;

            // compute absolute vocalsUrl
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

            // reset duration so geometry recomputed on load
            duration = 0;
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
            console.error("fetchResult error:", err);
            return null;
        }
    }

    async function startAnalysis(e) {
        e.preventDefault();
        analysisError = null;
        analysisRunning = true;

        searchResults = [];
        videoPreview = null;

        if (loading || !authToken) {
            analysisError = "Authentication not ready. Please wait.";
            analysisRunning = false;
            return;
        }

        let urlToSend;
        if (videoPreview) {
            urlToSend = `https://www.youtube.com/watch?v=${videoPreview.id}`;
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

            eventSource = new EventSource(`${apiUrl}/audio/progress/${taskId}`);

            eventSource.onmessage = async (event) => {
                progress = event.data;

                if (progress === "done") {
                    if (eventSource) eventSource.close();
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

    function startResultPoll(taskIdParam, timeoutMs = 30000) {
        let elapsed = 0;
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(async () => {
            elapsed += 1000;
            const got = await fetchResult(taskIdParam);
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

    // small utility for display
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

    // --- hook to receive AudioPlayer's element (the component dispatches "element")
    function onPlayerElement(event) {
        const el = event.detail?.element;
        if (!el) return;
        audioElem = el;

        // attach metadata handler (we want to compute geometry once duration known)
        audioElem.onloadedmetadata = () => {
            handleAudioLoadedMetadata();
        };
        audioElem.ontimeupdate = handleTimeUpdate;
        audioElem.onerror = handleAudioError;

        // if already has metadata ready
        if (audioElem.readyState >= 1) {
            handleAudioLoadedMetadata();
        }
    }
</script>

<div class="w-full my-auto bg-white">
    {#if !vocalsUrl}
        <h1
            class="pb-8 text-center text-6xl text-capitalize text-fuchsia-400 font-bold"
        >
            Paste Your Link
        </h1>

        <form
            on:submit={startAnalysis}
            class="flex items-start w-1/2 max-w-3xl mx-auto space-x-2 mb-6"
        >
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

                    {#if !analysisRunning && searchResults.length > 0 && !isUrl}
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

                    {#if analysisRunning || progress}
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
    {:else}
        <div class="w-full bg-white">
            <h1 class="font-bold text-5xl text-fuchsia-400 mb-2">
                Vocal Results
            </h1>

            <!-- NEW: use AudioPlayer component, receive element through on:element -->

            {#if notes && notes.length > 0}
                <div class="mt-4">
                    <AudioPlayer src={vocalsUrl} on:element={onPlayerElement}>
                        <div slot="timeline">
                            {#each notes as note, i}
                                <div
                                    class="timeline-interval absolute top-1/2 transform -translate-y-1/2"
                                    style="left: {note.left}%; width: {note.width}%;"
                                >
                                    <button
                                        class="interval-btn w-full h-full flex items-center justify-center text-xs font-semibold"
                                        on:click={() => playInterval(i)}
                                        aria-label={`Play ${note.note} from ${note.start} to ${note.end}`}
                                        title={`${note.note} — ${note.start} → ${note.end}`}
                                    >
                                        <span class="interval-label"
                                            >{note.note}</span
                                        >
                                    </button>
                                </div>
                            {/each}
                        </div>
                    </AudioPlayer>

                    <h4 class="text-sm font-medium mb-2">
                        Detected notes timeline
                    </h4>

                    <ul class="mt-3 divide-y">
                        {#each notes as note, i}
                            <li class="py-2 flex items-center justify-between">
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
                                        on:click={() => playInterval(i, true)}
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
</div>

<style>
    /* keep your mockup styles exactly the same */
    .timeline-interval {
        height: 48%;
        background: rgba(232, 121, 249, 0.95);
        border-radius: 6px;
        overflow: hidden;
        min-width: 6px;
        border: 1px solid rgba(0, 0, 0, 0.08);
        z-index: 11;
        position: absolute;
        top: 1.25rem; /* align inside the 12 height + padding -- tweak if necessary */
    }

    :global(.interval-btn) {
        background: transparent;
        color: #fff;
        padding: 0 6px;
        height: 100%;
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
    }

    :global(.interval-btn:focus) {
        outline: 2px solid rgba(232, 121, 249, 0.6);
    }

    .interval-label {
        pointer-events: none;
        font-weight: 600;
        font-size: 10px;
    }

    /* progress UI */
    .glass-progress-bar {
        background: linear-gradient(90deg, #a855f7, #f472b6);
    }
</style>
