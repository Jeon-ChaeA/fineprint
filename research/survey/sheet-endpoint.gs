/**
 * fineprint 설문 응답 수집용 Google Apps Script
 *
 * 설문 페이지에서 보낸 응답을 Google 스프레드시트에 저장한다.
 * - responses 시트: 1차 사용자 설문 (survey/index.html, 2026-10-08 마감)
 * - usability 시트: 프로토타입 사용성 테스트 설문 (survey/usability.html, form: "usability")
 * - usability3 시트: 실제 사람 테스트, 이해도 퀴즈 (survey/usability3.html, form: "usability3")
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
// 실제 사람 테스트 (research/usability/test-3-plan.md)
const U3_FIELDS = [
  'loan_exp', 'group', 'pre_q1', 'pre_q2', 'pre_q3', 'pre_q4', 'pre_q5', 'pre_score',
  'material_seconds', 'opened_link', 'post_q1', 'post_q2', 'post_q3', 'post_q4', 'post_q5', 'post_score',
  'asked_own', 'own_question', 'answer_status', 'answer_help', 'next_step_help', 'trust_source',
  'compare_pref', 'would_use', 'one_fix', 'ua_mobile'
];

// 폼별 시트와 마감 인원. 마감 뒤 응답은 저장하지 않고, 설문 페이지는 마감 안내를 보여 준다.
const FORMS = {
  responses: { fields: FIELDS, limit: 0 },
  usability: { fields: USABILITY_FIELDS, limit: 5 },
  usability3: { fields: U3_FIELDS, limit: 12 }
};

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const data = JSON.parse(e.postData.contents || '{}');
    if (data._hp) return ok_();  // 스팸 봇이 채우는 숨은 필드

    const ss = SpreadsheetApp.openById(SHEET_ID);
    const now = new Date();

    const name = FORMS[data.form] ? data.form : 'responses';
    const form = FORMS[name];
    const sh = sheet_(ss, name, ['received_at'].concat(form.fields));
    if (form.limit && sh.getLastRow() - 1 >= form.limit) return json_({ ok: false, closed: true });
    sh.appendRow([now].concat(form.fields.map(function (k) { return clean_(data[k]); })));

    return ok_();
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ ok: false }))
      .setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}

function doGet(e) {
  // 설문 페이지가 열릴 때 마감 여부와 응답 수를 묻는다: ?status=usability3
  const st = e && e.parameter && e.parameter.status;
  if (st && FORMS[st] && FORMS[st].limit) {
    const sh = SpreadsheetApp.openById(SHEET_ID).getSheetByName(st);
    const count = sh ? Math.max(0, sh.getLastRow() - 1) : 0;
    return json_({ open: count < FORMS[st].limit, count: count, limit: FORMS[st].limit });
  }
  return ContentService.createTextOutput('fineprint survey endpoint is running.');
}

/** 배포 전에 한 번 실행해 권한을 승인하고 시트를 준비한다. */
function setup() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  ss.setSpreadsheetTimeZone('Asia/Seoul');
  Object.keys(FORMS).forEach(function (name) {
    sheet_(ss, name, ['received_at'].concat(FORMS[name].fields));
  });
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
