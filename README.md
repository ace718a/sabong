# sabong

## Sitemap automation

- HTML 파일이 `main` 브랜치에 push되면 GitHub Actions가 `sitemap.xml`을 자동 갱신합니다.
- `index.html`은 `https://sabong.co.kr/`로 변환됩니다.
- 하위 폴더의 `index.html`은 해당 폴더 URL(`/folder/`)로 변환됩니다.
- 현재 메인에서 비노출 중인 `about.html`, `privacy.html`은 사이트맵 자동 생성 대상에서 제외했습니다.
- `robots.txt`의 사이트맵 주소는 `https://sabong.co.kr/sitemap.xml` 그대로 유지됩니다.
