# Release Rules
<!-- last-analyzed: 2026-09-18T06:00:00Z -->
<!-- delta 확인(2026-09-18): release.yml 최종 변경은 여전히 d3ab43e(2026-08-10)로
     규칙 변화 없음. 테스트 건수만 현재 값으로 갱신했다(린트 기준선 10건은 그대로). -->

## Version Sources
- `version.py` — `__version__ = "X.Y.Z"` (단일 출처)
- `installer.iss` 는 CI에서 `/DAppVersion=` 파라미터로 주입되므로 수동 수정 불필요

## ⚠ 태그를 붙이기 전에 반드시 version.py를 먼저 올린다
릴리즈 워크플로에 **"Verify version.py matches tag"** 스텝이 있어, 태그(`vX.Y.Z`)와
`version.py`의 `__version__`이 다르면 빌드가 그 자리에서 실패한다:
```
version.py does not contain 'X.Y.Z' — update version.py before tagging
```
**v1.23.0에서 실제로 이 사고가 났다.** 태그와 GitHub Release 페이지는 생성됐지만 빌드가
1분 만에 죽어 **자산이 0개**였고, "Latest" 릴리즈에 내려받을 인스톨러가 없어 자동 업데이트가
조용히 실패했다. 순서는 항상 ① version.py 수정 → ② 커밋·푸시 → ③ 태그 → ④ 태그 푸시다.

**이미 잘못된 태그를 붙였다면**: 태그를 *삭제하지 말고* `git tag -f vX.Y.Z` +
`git push --force origin vX.Y.Z`로 **이동**시킨다(삭제하면 기존 Release 페이지가 태그를
잃는다). 태그 이동도 push 이벤트라 워크플로가 재실행되고, `softprops/action-gh-release`가
같은 태그의 기존 릴리즈를 자산과 함께 갱신한다.

## Release Trigger
- `v*.*.*` 태그 푸시 → `.github/workflows/release.yml` 자동 실행
- 태그 **이동**(force push)도 동일하게 트리거된다

## Test Gate
- CI 릴리즈 워크플로우에 test step 없음 — 빌드 성공만이 게이트다.
  따라서 **로컬에서 전체 테스트를 돌리고 릴리즈해야 한다**: `pytest` (2026-09-19 기준 2,495건)
- 린트: `ruff check gui/ application/` — 이 저장소는 `ruff format` 미적용이라
  기존 E402가 기준선이다(2026-09-18 기준 10건 — 조립 루트 분해로 main.py 8건이 사라졌다).
  "새 위반이 늘지 않았는가"로만 판단한다.

## 네이티브 의존이 늘었을 때의 추가 게이트 (v1.27.0~)
음성 인식(faster-whisper→ctranslate2·onnxruntime·av)처럼 **네이티브 확장**을 번들에
추가하면, CI 빌드가 성공해도 실행 시 DLL 로드에 실패해 기능이 **조용히** 죽을 수 있다.
그런 변경이 있으면 태그 전에 로컬에서 확인한다:
```powershell
.\scripts\build_windows.ps1
dist\windows\YouTubeContentManager\YouTubeContentManager.exe   # 실제 실행 파일은 하위 폴더다
```
- **실제 실행 파일은 `dist\windows\YouTubeContentManager\`** 안에 있다. `dist\windows\`
  바로 아래 exe 는 COLLECT 이전 부트로더 잔여물이라 `_internal` 없이 즉시 죽는다.
- 순수 파이썬 패키지는 `_internal` 에 폴더로 보이지 않는다(PYZ 아카이브에 들어간다) —
  폴더 존재로 판정하면 오탐이다.
- 네이티브 확장은 **import 성공만으로 부족**하다. 함수를 실제로 호출해 봐야 한다
  (예: `ctranslate2.get_supported_compute_types('cpu')`).

## Registry / Distribution
- GitHub Releases — `softprops/action-gh-release@v2`
- 산출물: `dist/YouTubeContentManager-setup.exe` + `.sha256` + `version.txt`
- CI job: `build-windows` (windows-latest)

## Release Notes Strategy
- GitHub 자동 생성 (`generate_release_notes: true`)
- 릴리즈 제목: `YouTube Content Manager X.Y.Z`

## CI Workflow Files
- `.github/workflows/release.yml`

## Required Secrets
- `YOUTUBE_OAUTH_CLIENT_JSON` — 로컬 `data/OAuth2.json`(Desktop OAuth 클라이언트,
  `data/OAuth.json`과 다름) 내용 그대로. CI가 `$RUNNER_TEMP/OAuth2.json`으로 복원해
  `OVC_YOUTUBE_OAUTH_CONFIG`로 PyInstaller에 전달한다. 없으면 빌드가 즉시 실패
  ("Write YouTube OAuth client config from secret" 스텝에서 명확한 에러로 중단).
  값은 어떤 스텝에서도 출력하지 않는다. `gh secret set YOUTUBE_OAUTH_CLIENT_JSON
  --repo <owner>/<repo> < data/OAuth2.json`로 등록(2026-08-10 최초 등록).

## First-Time Setup Gaps
- none (2026-08-10: YOUTUBE_OAUTH_CLIENT_JSON 시크릿 최초 등록 완료)
