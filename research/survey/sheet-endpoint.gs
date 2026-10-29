/**
 * fineprint 설문 응답 수집용 Google Apps Script
 *
 * 설문 페이지에서 보낸 응답을 Google 스프레드시트에 저장한다.
 * - responses 시트: 1차 사용자 설문 (survey/index.html, 2026-10-08 마감)
 * - usability 시트: 프로토타입 사용성 테스트 설문 (survey/usability.html, form: "usability")
 *
 * 설정 방법은 research/survey/README.md 참고.
 */
// 응답을 저장할 스프레드시트 ID (주소의 /d/ 와 /edit 사이)
const SHEET_ID = 'YOUR_SHEET_ID';

const FIELDS = [
  'loan_exp', 'products', 'read_level', 'skip_reasons', 'check_items',
  'surprised', 'surprised_story', 'summary_left', 'summary_question',
  'help_wanted', 'help_top', 'trust_needs', 'age', 'job', 'ua_mobile'
];

// 사용성 테스트 설문 (research/usability/README.md)
const USABILITY_FIELDS = [
  'loan_exp', 'bank', 'worry_topic', 'opened_source', 'trust_source', 'summary_clear', 'confusing_line',
  'understood_check', 'used_samples', 'tried_own_question', 'own_question', 'cannot_judge_feel',
  'summary_vs_ask', 'would_use', 'one_fix', 'ua_mobile'
];
// 사용성 테스트는 5명에서 마감한다. 이후 응답은 저장하지 않고, 설문 페이지는 마감 안내를 보여 준다.
const USABILITY_LIMIT = 5;

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const data = JSON.parse(e.postData.contents || '{}');
    if (data._hp) return ok_();  // 스팸 봇이 채우는 숨은 필드

    const ss = SpreadsheetApp.openById(SHEET_ID);
    const now = new Date();

    const usability = data.form === 'usability';
    const name = usability ? 'usability' : 'responses';
    const fields = usability ? USABILITY_FIELDS : FIELDS;
    const sh = sheet_(ss, name, ['received_at'].concat(fields));
    if (usability && sh.getLastRow() - 1 >= USABILITY_LIMIT) return json_({ ok: false, closed: true });
    sh.appendRow([now].concat(fields.map(function (k) { return clean_(data[k]); })));

    return ok_();
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ ok: false }))
      .setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}

function doGet(e) {
  // 설문 페이지가 열릴 때 마감 여부를 묻는다: ?status=usability
  if (e && e.parameter && e.parameter.status === 'usability') {
    const sh = SpreadsheetApp.openById(SHEET_ID).getSheetByName('usability');
    const count = sh ? Math.max(0, sh.getLastRow() - 1) : 0;
    return json_({ open: count < USABILITY_LIMIT, count: count, limit: USABILITY_LIMIT });
  }
  return ContentService.createTextOutput('fineprint survey endpoint is running.');
}

/** 배포 전에 한 번 실행해 권한을 승인하고 시트를 준비한다. */
function setup() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  ss.setSpreadsheetTimeZone('Asia/Seoul');
  sheet_(ss, 'responses', ['received_at'].concat(FIELDS));
  sheet_(ss, 'usability', ['received_at'].concat(USABILITY_FIELDS));
}

function sheet_(ss, name, header) {
  let sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  if (sh.getLastRow() === 0) {
    sh.appendRow(header);
    sh.setFrozenRows(1);
  }
  return sh;
}

/** 문자열로 바꾸고 길이를 자르고, 수식으로 해석될 수 있는 값은 막는다. */
function clean_(v) {
  let s = v == null ? '' : String(v);
  s = s.slice(0, 2000);
  if (/^[=+\-@]/.test(s)) s = "'" + s;
  return s;
}

function ok_() {
  return json_({ ok: true });
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
