import concurrent.futures
import json

from client import AppleMusicClient


def main():
    client = AppleMusicClient()

    # Test artist parsing
    artist_url = "https://music.apple.com/us/artist/ed-sheeran/183313439"
    print(f"Testing artist page: {artist_url}")
    artist_releases = client.get_artist_new_releases(artist_url, "us")
    print(f"Found {len(artist_releases)} releases for artist.")
    for r in artist_releases[:5]:
        print(f" - {r['title']} ({r['storeAdamID']})")

    print("\nIf you'd like to run the full room aggregation again, uncomment the room code below.")

    rooms = {
        "hk": "https://music.apple.com/hk/room/6760511635",
        "jp": "https://music.apple.com/jp/room/6760491280",
        "my": "https://music.apple.com/my/room/6760483004",
        "tw": "https://music.apple.com/tw/room/6760510169"
    }

    all_releases = {}
    print("Fetching room items...")
    for sf, url in rooms.items():
        rels = client.get_room_new_releases(url, sf)
        print(f"[{sf.upper()}] Extracted {len(rels)} releases.")
        for r in rels:
            # aggregate
            aid = r['storeAdamID']
            if aid in all_releases:
                if sf not in all_releases[aid]['storefronts']:
                    all_releases[aid]['storefronts'].append(sf)
            else:
                all_releases[aid] = r

    rel_list = list(all_releases.values())
    print(f"\nTotal unique releases: {len(rel_list)}")

    print("Fetching album details to extract release dates (this may take a minute)...")
    # Fetch dates concurrently to save time
    def fetch_date_for_release(r):
        r['releaseDate'] = client.get_album_release_date(r['url'])
        return r

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        rel_list = list(executor.map(fetch_date_for_release, rel_list))

    # Sort by release date (reverse, newest first)
    rel_list.sort(key=lambda x: str(x.get('releaseDate', '')), reverse=True)

    # Save to disk
    with open('aggregated_new_releases.json', 'w', encoding='utf-8') as f:
        json.dump(rel_list, f, indent=2, ensure_ascii=False)

    print(f"\nSaved aggregated_new_releases.json with {len(rel_list)} releases, sorted by date.")
    print("\nTop 5 newest releases:")
    for r in rel_list[:5]:
        print(f"- {r['releaseDate']} | {r['title']} by {r['artist']} ({', '.join(r['storefronts'])}) [{r['storeAdamID']}]")


if __name__ == "__main__":
    main()
