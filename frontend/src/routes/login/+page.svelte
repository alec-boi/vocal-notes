<script>
    import { supabase } from "../../lib/subabaseClient";
    import { onMount } from "svelte";

    let email = "";
    let message = "";

    async function signInWithGoogle() {
        const { error } = await supabase.auth.signInWithOAuth({
            provider: "google",
        });
        if (error) message = error.message;
    }

    async function signInWithEmail() {
        const { error } = await supabase.auth.signInWithOtp({ email });
        message = error
            ? error.message
            : "Check your email for the magic link!";
    }

    onMount(async () => {
        const { data } = await supabase.auth.getSession();
        if (data.session) window.location.href = "/";
    });
</script>

<div class="p-6 max-w-sm mx-auto space-y-4">
    <h1 class="text-2xl font-bold text-center">Login</h1>

    <input
        class="border p-2 w-full"
        type="email"
        bind:value={email}
        placeholder="Your email"
    />

    <button
        on:click={signInWithEmail}
        class="bg-blue-600 text-white px-4 py-2 w-full rounded"
    >
        Magic Link Login
    </button>

    <button
        on:click={signInWithGoogle}
        class="bg-red-500 text-white px-4 py-2 w-full rounded"
    >
        Continue with Google
    </button>

    <p class="text-center text-sm text-gray-600">{message}</p>
</div>
