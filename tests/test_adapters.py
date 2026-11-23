"""适配器：输出解析、用例名提取、函数切分、覆盖率。"""

from __future__ import annotations

from actuallydone.adapters import CAP_TESTS, get
from actuallydone.adapters.cpp_adapter import CppAdapter
from actuallydone.adapters.go_adapter import GoAdapter, func_name, total_percent
from actuallydone.adapters.java_adapter import JavaAdapter
from actuallydone.adapters.node_adapter import NodeAdapter
from actuallydone.adapters.python_adapter import PythonAdapter
from tests.helpers import (CTEST_TEST_OUTPUT, GO_TEST_OUTPUT, GRADLE_TEST_OUTPUT,
                           GTEST_TEST_OUTPUT, JAVA_JACOCO_XML, MAVEN_TEST_OUTPUT,
                           NODE_TEST_OUTPUT, ProjectCase)


class TestGoAdapter(ProjectCase):
    def test_解析测试输出要分开顶层与子用例的跳过数(self):
        res = GoAdapter(self.root).parse_test_output(GO_TEST_OUTPUT)
        self.assertEqual(res.passed, 3)      # TestAdd、TestSub、TestSub/负数
        self.assertEqual(res.failed, 1)
        self.assertEqual(res.skipped, 1)
        self.assertEqual(res.skip_top, 1)
        self.assertEqual(res.coverage, 85.9)
        self.assertIn("TestSub/负数", res.passed_names)

    def test_多包覆盖率不取最后一行(self):
        text = ("ok  \tpkg/a\t0.1s\tcoverage: 10.0% of statements\n"
                "--- PASS: TestA\n"
                "ok  \tpkg/b\t0.1s\tcoverage: 100.0% of statements\n"
                "--- PASS: TestB\n")
        res = GoAdapter(self.root).parse_test_output(text)
        self.assertIsNone(res.coverage)
        self.assertEqual(res.passed, 2)

    def test_cover_func的total行是总覆盖率(self):
        text = ("pkg/a.go:1:\tA\t0.0%\n"
                "pkg/b.go:1:\tB\t100.0%\n"
                "total:\t\t\t\t\t(statements)\t40.0%\n")
        self.assertEqual(total_percent(text), 40.0)
        self.assertIsNone(total_percent("ok  coverage: 100.0% of statements\n"))

    def test_没开verbose时判为解析不出而不是零通过(self):
        res = GoAdapter(self.root).parse_test_output("ok  \tfixture/internal\t0.3s\n")
        self.assertFalse(res.parsed)

    def test_列出用例名(self):
        self.make_go_project()
        names = GoAdapter(self.root).test_names([self.root / "internal"])
        self.assertEqual(names, {"TestAdd", "TestNoAssert", "TestSkipped"})

    def test_related_tests按实现文件找同stem测试(self):
        self.make_go_project()
        ad = GoAdapter(self.root)
        names = ad.related_tests(["internal/calc.go"])
        self.assertEqual(set(names), {"TestAdd", "TestNoAssert", "TestSkipped"})
        argv = ad.related_test_argv(names)
        self.assertIn("-run", argv)
        self.assertTrue(any("TestAdd" in a for a in argv))
        self.assertEqual(ad.related_tests(["internal/orphan.go"]), [])

    def test_无断言用例能被认出来(self):
        self.make_go_project()
        ad = GoAdapter(self.root)
        funcs = {f.name: f for f in ad.iter_test_funcs(self.root / "internal/calc_test.go")}
        self.assertTrue(ad.is_assertionless(funcs["TestNoAssert"].body))
        self.assertFalse(ad.is_assertionless(funcs["TestAdd"].body))

    def test_方法名要跳过接收者(self):
        self.assertEqual(func_name("func (w *Worker) Start(ctx context.Context) {"), "Start")
        self.assertEqual(func_name("func Add(a, b int) int {"), "Add")

    def test_提取路由字面量(self):
        self.write("api/routes.go", '''package api
func reg(r chi.Router) {
	r.Get("/listing-tasks", h.list)
	r.Post("/listing-tasks/{id}/publish", h.publish)
}
''')
        got = GoAdapter(self.root).routes(self.root / "api")
        self.assertEqual(got, {"/listing-tasks", "/listing-tasks/{id}/publish"})


class TestNodeAdapter(ProjectCase):
    def test_汇总行优先于逐条行(self):
        res = NodeAdapter(self.root).parse_test_output(NODE_TEST_OUTPUT)
        self.assertEqual(res.passed, 2)
        self.assertEqual(res.failed, 1)

    def test_列出用例标题与页面(self):
        self.make_node_project()
        ad = NodeAdapter(self.root)
        self.assertEqual(ad.test_names([self.root / "src"]), {"拒绝负数价格"})
        self.assertEqual(ad.views(self.root / "src"), {"OrderView.vue"})

    def test_related_tests按同stem的test文件(self):
        self.make_node_project()
        ad = NodeAdapter(self.root)
        self.assertEqual(ad.related_tests(["src/order.ts"]), ["拒绝负数价格"])
        self.assertEqual(ad.related_tests(["src/missing.ts"]), [])

    def test_读lcov算零覆盖函数(self):
        p = self.write("cov/lcov.info", "\n".join([
            "SF:src/a.ts", "FN:1,foo", "FN:9,bar", "FNDA:3,foo", "FNDA:0,bar",
            "end_of_record",
        ]))
        self.assertEqual(NodeAdapter(self.root).zero_cover(p, self.root), (1, 2))


class TestPythonAdapter(ProjectCase):
    def test_解析unittest输出(self):
        out = ("test_add (m.C) ... ok\n"
               "test_sub (m.C) ... FAIL\n"
               "test_x (m.C) ... skipped 'why'\n")
        res = PythonAdapter(self.root).parse_test_output(out)
        self.assertEqual((res.passed, res.failed, res.skipped), (1, 1, 1))

    def test_按缩进切函数体(self):
        p = self.write("m.py", "def f():\n    a = 1\n    return a\n\ndef g():\n    pass\n")
        funcs = {f.name: f.body for f in PythonAdapter(self.root).iter_funcs(p)}
        self.assertEqual(funcs["f"], ["a = 1", "return a"])

    def test_related_tests按test前缀配对(self):
        self.write("lib.py", "def add(a, b):\n    return a + b\n")
        self.write("test_lib.py", "def test_add():\n    assert True\n")
        ad = PythonAdapter(self.root)
        self.assertEqual(ad.related_tests(["lib.py"]), ["test_add"])
        argv = ad.related_test_argv(["test_add"])
        self.assertIn("-k", argv)
        self.assertEqual(ad.related_tests(["other.py"]), [])


class TestJavaAdapter(ProjectCase):
    def test_聚合行不带in才是全局合计(self):
        res = JavaAdapter(self.root).parse_test_output(MAVEN_TEST_OUTPUT)
        self.assertEqual((res.passed, res.failed, res.skipped), (1, 1, 1))

    def test_解析Gradle汇总行(self):
        res = JavaAdapter(self.root).parse_test_output(GRADLE_TEST_OUTPUT)
        self.assertEqual((res.passed, res.failed, res.skipped), (1, 1, 1))

    def test_逐类行不能被当成全局合计(self):
        # 只有带 -- in 的行，没有 Results 段：解析不出合计
        only_class = ("[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 0 "
                      "-- in com.example.CalcTest\n")
        res = JavaAdapter(self.root).parse_test_output(only_class)
        self.assertFalse(res.parsed)

    def test_Gradle静默成功时计数取自XML(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        res = ad.parse_test_run("BUILD SUCCESSFUL\n", cwd=self.root, since=0)
        self.assertTrue(res.parsed)
        self.assertEqual(res.passed, 2)
        self.assertEqual(res.skipped, 1)
        self.assertIn("CalcTest#testAdd", res.passed_names)
        self.assertIn("CalcTest#加法", res.passed_names)

    def test_XML与控制台对不上时有计数无名字(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        # 控制台说 10 通过，XML 只有 2：对不上
        res = ad.parse_test_run(
            "Tests run: 10, Failures: 0, Errors: 0, Skipped: 0\n",
            cwd=self.root, since=0)
        self.assertEqual(res.passed, 10)
        self.assertEqual(res.passed_names, [])

    def test_旧XML不参与解析(self):
        self.make_maven_project()
        report = self.root / "target/surefire-reports/TEST-com.example.CalcTest.xml"
        import os
        os.utime(report, (1_000_000, 1_000_000))   # 1970 年代
        res = JavaAdapter(self.root).parse_test_run(
            "BUILD SUCCESSFUL\n", cwd=self.root, since=1_700_000_000)
        self.assertFalse(res.parsed)

    def test_related_tests实现对上Test后缀类(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        self.assertIn("CalcTest", ad.related_tests(["src/main/java/com/example/Calc.java"]))
        self.assertIn("CalcTest", ad.related_tests(
            ["src/test/java/com/example/CalcTest.java"]))
        argv = ad.related_test_argv(["CalcTest", "OtherTest"])
        self.assertTrue(any(a.startswith("-Dtest=") and "CalcTest" in a for a in argv), argv)
        self.assertEqual(ad.related_tests(["src/main/java/com/example/Orphan.java"]), [])

    def test_源码与XML的名字形式一致且含DisplayName(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        names = ad.test_names([self.root / "src"])
        self.assertIn("CalcTest#testAdd", names)
        self.assertIn("CalcTest#testPlus", names)
        self.assertIn("CalcTest#加法", names)
        xml = ad.parse_test_run("BUILD SUCCESSFUL\n", cwd=self.root, since=0)
        for n in xml.passed_names:
            self.assertIn(n, names)

    def test_andExpect不算无断言_Disabled计入跳过(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        p = self.root / "src/test/java/com/example/CalcTest.java"
        funcs = {f.name: f for f in ad.iter_test_funcs(p)}
        self.assertFalse(ad.is_assertionless(funcs["testPlus"].body))
        self.assertTrue(ad.is_assertionless(funcs["testNoAssert"].body))
        self.assertGreaterEqual(ad.skip_sites(p.read_text(encoding="utf-8")), 1)

    def test_jacoco零覆盖与行覆盖率(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        self.assertEqual(ad.zero_cover(self.root / "cover.out", self.root), (1, 2))
        res = ad.parse_test_run(MAVEN_TEST_OUTPUT, cwd=self.root, since=0)
        self.assertEqual(res.coverage, 85.0)

    def test_非常规路径的jacoco也能找到(self):
        self.write("reports/coverage/jacoco.xml", JAVA_JACOCO_XML)
        ad = JavaAdapter(self.root)
        self.assertEqual(ad.coverage_from_reports(self.root), 85.0)

    def test_多模块的覆盖率是各模块加起来而不是第一个模块(self):
        """以前返回「第一份能解析的报告」，在多模块仓库里报的是字母序第一个模块，
        既不是整体水位，还会随模块改名而跳变。"""
        self.write("mod-a/target/site/jacoco/jacoco.xml",
                   JAVA_JACOCO_XML.replace('missed="15" covered="85"',
                                           'missed="0" covered="100"'))
        self.write("mod-b/target/site/jacoco/jacoco.xml",
                   JAVA_JACOCO_XML.replace('missed="15" covered="85"',
                                           'missed="100" covered="0"'))
        # 100 覆盖 + 100 未覆盖 = 50%；取第一个模块会得到 100.0
        self.assertEqual(JavaAdapter(self.root).coverage_from_reports(self.root), 50.0)

    def test_有聚合报告时不把模块报告重复计进去(self):
        self.write("mod-a/target/site/jacoco/jacoco.xml", JAVA_JACOCO_XML)
        self.write("target/site/jacoco-aggregate/jacoco.xml",
                   JAVA_JACOCO_XML.replace('missed="15" covered="85"',
                                           'missed="50" covered="50"'))
        self.assertEqual(JavaAdapter(self.root).coverage_from_reports(self.root), 50.0)

    def test_探针没挂上时点名prepare_agent(self):
        """mvn test jacoco:report 在 pom 没绑 prepare-agent 时会打一行 Skipping
        然后 BUILD SUCCESS——命令成功了，覆盖率却无从谈起。"""
        self.make_maven_project()
        (self.root / "target/site/jacoco/jacoco.xml").unlink()
        out = ("[INFO] --- jacoco:0.8.11:report (default-cli) @ fixture ---\n"
               "[INFO] Skipping JaCoCo execution due to missing execution data file.\n"
               "[INFO] BUILD SUCCESS\n")
        said = JavaAdapter(self.root).coverage_diagnosis(self.root, output=out)
        self.assertIn("prepare-agent", said)

    def test_只有exec没有xml时说清是report没跑(self):
        self.write("pom.xml", "<project/>")
        self.write("target/jacoco.exec", "二进制内容无关")
        said = JavaAdapter(self.root).coverage_diagnosis(self.root)
        self.assertIn("jacoco.exec", said)
        self.assertIn("jacoco:report", said)

    def test_一份报告都没有时说去哪找了(self):
        self.write("pom.xml", "<project/>")
        said = JavaAdapter(self.root).coverage_diagnosis(self.root)
        self.assertIn("jacoco.xml", said)
        self.assertIn("jacoco-maven-plugin", said)

    def test_端口冲突诊断说到Spring上下文缓存(self):
        said = JavaAdapter(self.root).failure_diagnosis(
            "APPLICATION FAILED TO START\nPort 8080 was already in use.\n")
        self.assertIsNotNone(said)
        self.assertIn("8080", said)
        self.assertIn("RANDOM_PORT", said)

    def test_通用端口冲突所有适配器都能认(self):
        from actuallydone.adapters.base import Adapter
        said = Adapter(self.root).failure_diagnosis("BindException: Address already in use")
        self.assertIsNotNone(said)
        self.assertIn("被占", said)

    def test_耗时榜按time属性排序并带模块名(self):
        self.write("mod-a/target/surefire-reports/TEST-A.xml",
                   '''<?xml version="1.0"?>
<testsuite name="A"><testcase name="slow" classname="com.A" time="3.5"/>
<testcase name="fast" classname="com.A" time="0.01"/></testsuite>''')
        self.write("mod-b/target/surefire-reports/TEST-B.xml",
                   '''<?xml version="1.0"?>
<testsuite name="B"><testcase name="mid" classname="com.B" time="1.2"/></testsuite>''')
        rows = JavaAdapter(self.root).slowest_tests(self.root, since=0, n=3)
        self.assertEqual(rows[0][0], "A#slow")
        self.assertAlmostEqual(rows[0][1], 3.5)
        self.assertEqual(rows[0][2], "mod-a")
        self.assertEqual([r[0] for r in rows], ["A#slow", "B#mid", "A#fast"])

    def test_jacoco_csv也能算出行覆盖率(self):
        self.write("target/site/jacoco/jacoco.csv",
                   "GROUP,PACKAGE,CLASS,INSTRUCTION_MISSED,INSTRUCTION_COVERED,"
                   "BRANCH_MISSED,BRANCH_COVERED,LINE_MISSED,LINE_COVERED,"
                   "COMPLEXITY_MISSED,COMPLEXITY_COVERED,METHOD_MISSED,METHOD_COVERED\n"
                   "app,com.example,Calc,0,10,0,0,15,85,0,0,0,1\n")
        self.assertEqual(JavaAdapter(self.root).coverage_from_reports(self.root), 85.0)

    def test_Spring类级前缀拼接(self):
        self.write("src/main/java/com/example/Api.java", '''
@RequestMapping("/api")
class Api {
    @GetMapping("/orders")
    void list() {}
    @PostMapping(value = "/orders")
    void create() {}
}
''')
        got = JavaAdapter(self.root).routes(self.root / "src")
        self.assertIn("/api/orders", got)

    def test_单跑命令Maven精确与显示名降级(self):
        self.make_maven_project()
        ad = JavaAdapter(self.root)
        self.assertEqual(ad.single_test_argv("CalcTest#testAdd"),
                         ["mvn", "-B", "-ntp", "test",
                          "-Dtest=CalcTest#testAdd", "-DfailIfNoTests=false"])
        argv = ad.single_test_argv("CalcTest#加法")
        self.assertEqual(argv[-2], "-Dtest=CalcTest")

    def test_单跑命令Gradle(self):
        self.make_gradle_project()
        ad = JavaAdapter(self.root)
        self.assertIn("--tests", ad.single_test_argv("CalcTest#testAdd"))
        self.assertIn("*.CalcTest.testAdd", ad.single_test_argv("CalcTest#testAdd"))
        self.assertIn("*.CalcTest", ad.single_test_argv("CalcTest#加法"))

    def test_探测建议步骤含mvn_test且不用fmt(self):
        self.make_maven_project()
        steps = JavaAdapter(self.root).suggest_steps(".")
        names = [s["name"] for s in steps]
        self.assertIn("mvn test", names)
        self.assertIn("spotless:check", names)
        test = next(s for s in steps if s["name"] == "mvn test")
        self.assertEqual(test["kind"], "test")
        self.assertEqual(test["adapter"], "java")
        self.assertIn("jacoco:report", test["argv"])
        # prepare-agent 必须显式写在 CLI 上且排在 test 前面：pom 只声明插件却没绑它时，
        # mvn test 不挂探针，jacoco:report 只打一行 Skipping 就成功了
        argv = test["argv"]
        self.assertIn("jacoco:prepare-agent", argv)
        self.assertLess(argv.index("jacoco:prepare-agent"), argv.index("test"))
        self.assertFalse(any(s.get("kind") == "fmt" for s in steps))

    def test_监视src而不是模块根(self):
        self.make_maven_project()
        roots, exts = JavaAdapter(self.root).suggest_watch(".")
        self.assertEqual(roots, ["src"])
        self.assertIn(".java", exts)
        self.assertIn(".kt", exts)


class TestCppAdapter(ProjectCase):
    def test_解析GoogleTest输出(self):
        res = CppAdapter(self.root).parse_test_output(GTEST_TEST_OUTPUT)
        self.assertEqual(res.passed, 1)
        self.assertEqual(res.failed, 1)
        self.assertEqual(res.skipped, 1)
        self.assertIn("Calc.Add", res.passed_names)
        self.assertIn("Calc.Sub", res.failed_names)
        self.assertIn("Calc.Skip", res.skipped_names)

    def test_解析CTest输出(self):
        res = CppAdapter(self.root).parse_test_output(CTEST_TEST_OUTPUT)
        self.assertEqual(res.passed, 1)
        self.assertEqual(res.failed, 1)
        self.assertEqual(res.skipped, 1)
        self.assertIn("Calc.Add", res.passed_names)

    def test_CTest前缀的GTest行也能认(self):
        text = "1: [       OK ] TaskStore.Add (0 ms)\n1: [  FAILED  ] TaskStore.Buy\n"
        res = CppAdapter(self.root).parse_test_output(text)
        self.assertEqual(res.passed_names, ["TaskStore.Add"])
        self.assertEqual(res.failed_names, ["TaskStore.Buy"])

    def test_列出用例名含GTest与Catch(self):
        self.make_cmake_project()
        names = CppAdapter(self.root).test_names([self.root / "tests"])
        self.assertEqual(names, {"Calc.Add", "Calc.NoAssert", "catch-add"})

    def test_related_tests按stem对上测试文件(self):
        self.make_cmake_project()
        ad = CppAdapter(self.root)
        names = set(ad.related_tests(["src/calc.cpp"]))
        self.assertTrue({"Calc.Add", "Calc.NoAssert"} <= names)
        argv = ad.related_test_argv(sorted(names))
        self.assertIn("-R", argv)
        self.assertEqual(ad.related_tests(["src/orphan.cpp"]), [])

    def test_无断言与跳过(self):
        self.make_cmake_project()
        ad = CppAdapter(self.root)
        p = self.root / "tests/calc_test.cpp"
        funcs = {f.name: f for f in ad.iter_test_funcs(p)}
        self.assertFalse(ad.is_assertionless(funcs["Calc.Add"].body))
        self.assertTrue(ad.is_assertionless(funcs["Calc.NoAssert"].body))
        self.write("tests/skip_test.cpp",
                   "TEST(Calc, X) { GTEST_SKIP(); }\n")
        self.assertGreaterEqual(ad.skip_sites(
            (self.root / "tests/skip_test.cpp").read_text(encoding="utf-8")), 1)

    def test_探测步骤三系统同一份argv(self):
        self.make_cmake_project()
        steps = CppAdapter(self.root).suggest_steps(".")
        names = [s["name"] for s in steps]
        self.assertEqual(names, ["cmake configure", "cmake build", "ctest"])
        test = steps[-1]
        self.assertEqual(test["adapter"], "cpp")
        self.assertIn("-C", test["argv"])
        self.assertIn("Release", test["argv"])
        self.assertIn("chdir", test["argv"])
        conf = steps[0]["argv"]
        self.assertIn("-DCMAKE_BUILD_TYPE=Release", conf)
        self.assertIn("--config", steps[1]["argv"])

    def test_监视src_include_tests(self):
        self.make_cmake_project()
        self.write("include/calc.hpp", "int add(int, int);\n")
        roots, exts = CppAdapter(self.root).suggest_watch(".")
        self.assertIn("src", roots)
        self.assertIn("tests", roots)
        self.assertIn("include", roots)
        self.assertIn(".cpp", exts)
        self.assertIn(".hpp", exts)

    def test_读lcov覆盖率(self):
        self.make_cmake_project()
        ad = CppAdapter(self.root)
        self.assertEqual(ad.coverage_from_reports(self.root), 75.0)
        self.assertEqual(ad.zero_cover(self.root / "build/lcov.info", self.root), (1, 2))


class TestRegistry(ProjectCase):
    def test_不认识的生态退回无能力基类而不是抛错(self):
        ad = get("cobol", self.root)
        self.assertEqual(ad.caps, set())
        self.assertIsNone(ad.test_names([self.root]))   # None 才能让上层标「未评估」

    def test_能力集合(self):
        self.assertIn(CAP_TESTS, get("go", self.root).caps)
        self.assertIn(CAP_TESTS, get("java", self.root).caps)
        self.assertIn(CAP_TESTS, get("cpp", self.root).caps)
