# 사용자 설문

금융 약관을 실제로 어떻게 읽는지, 무엇을 몰라서 당황했는지, 어떤 도움을 원하는지 묻는 5분 설문이다.

- **설문 페이지**: [survey/index.html](../../survey/index.html)
  - 기본 주소 (Netlify): https://fineprint-survey.netlify.app/
  - 예비 주소 (GitHub Pages): https://jeon-chaea.github.io/fineprint/survey/
- **응답 저장**: [sheet-endpoint.gs](sheet-endpoint.gs) → Google 스프레드시트
- **설계 배경**: [앱 관찰](../app-observation.md)에서 나온 세 가지 빈틈(조항 찾기, 금융사 간 비교, 이해 확인)을 "하나만 고른다면?" 질문으로 검증한다.

## 개인정보 원칙

- 설문 답변은 익명이다. 이메일, 이름, 연락처는 받지 않는다.
- 응답 원본은 이 레포에 올리지 않는다. 집계 결과와 익명 인용만 올린다.

## 현재 상태

- **2026-10-08 마감.** 응답 39건. 설문 주소(Netlify, GitHub Pages)에는 마감 안내 페이지를 올렸다. [결과](../survey-results.md)
- 마감 전 설문 페이지 원본: [survey/index.html @ 93be8bd](https://github.com/Jeon-ChaeA/fineprint/blob/93be8bd78a880295b2903705ee0454b65fb17eb6/survey/index.html)
- 응답 시트: 개인 Google 계정의 `fineprint 설문 응답` (비공개)
- 수집 스크립트: Apps Script 프로젝트 `fineprint survey endpoint`, 웹 앱으로 배포 (실행: 나, 액세스: 모든 사용자)
- 설문 페이지의 `ENDPOINT`에 웹 앱 URL 연결 완료
- Netlify 프로젝트 `fineprint-survey`: `survey/index.html`을 직접 업로드(Netlify Drop)해 배포. 레포와 자동 연동되지 않으므로 **설문을 고치면 Netlify에도 다시 올려야 한다.**

## 처음부터 다시 설정할 때

1. Google 스프레드시트를 새로 만들고, 주소에서 시트 ID를 복사한다.
2. https://script.google.com 에서 새 프로젝트를 만들고 `sheet-endpoint.gs` 내용을 붙여 넣는다. `SHEET_ID`에 시트 ID를 넣는다.
3. `setup` 함수를 한 번 실행해 권한을 승인한다.
4. **배포 → 새 배포** → 유형 **웹 앱**, 실행 사용자 **나**, 액세스 권한 **모든 사용자**
5. 나온 웹 앱 URL을 `survey/index.html`의 `ENDPOINT`에 넣고 커밋한다.
6. 레포 **Settings → Pages** → Branch **main / (root)** → Save

## 확인

- 웹 앱 URL을 브라우저로 열면 `fineprint survey endpoint is running.`이 보여야 한다.
- 설문을 한 번 직접 제출해 보고 `responses` 시트에 한 줄이 생기는지 확인한다. 테스트 응답은 지운다.

## 이전 방식

[create-form.gs](create-form.gs)는 같은 질문으로 Google 폼을 만드는 스크립트다. 디자인을 직접 꾸미기 위해 HTML 페이지 방식으로 바꿨다.
