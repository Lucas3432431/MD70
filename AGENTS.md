<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

- Keep all investor financial figures behind the centralized mock data layer until a verified production source replaces it, so estimates are never confused with facts.
- Keep private investor pages under the integration-managed authenticated route layout, because client navigation alone is not an authorization boundary.
- Keep the investor portal and its nested project details in parent routes that render Outlet, because TanStack child pages need their parent layout to mount.
- Keep investor portal navigation in the shared bottom bar with category popups, because its sections should remain reachable at every screen size without crowding the bar.
- Keep the institutional mobile navigation in the shared site layout's bottom bar, because visitors need consistent navigation across public pages.
