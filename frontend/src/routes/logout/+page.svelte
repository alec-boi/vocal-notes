<script>
    import { onMount } from "svelte";
    import { supabase } from "../../lib/subabaseClient";

    onMount(async () => {
        await supabase.auth.signOut();
        window.location.href = "/login";
    });
</script>
