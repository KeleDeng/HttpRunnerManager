import json
import logging
import os

import sys
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render_to_response
from djcelery.models import PeriodicTask

from ApiManager.models import ProjectInfo, ModuleInfo, TestCaseInfo, UserInfo, EnvInfo, TestReports
from ApiManager.tasks import main_hrun
from ApiManager.utils.common import module_info_logic, project_info_logic, case_info_logic, config_info_logic, \
    set_filter_session, get_ajax_msg, register_info_logic, task_logic, load_configs, upload_file_logic, load_modules
from ApiManager.utils.operation import env_data_logic, del_module_data, del_project_data, del_test_data, copy_test_data, \
    del_report_data, add_upload_data
from ApiManager.utils.pagination import get_pager_info
from ApiManager.utils.runner import run_by_single, run_by_batch, run_by_module, run_by_project
from ApiManager.utils.task_opt import delete_task, change_task_status
from httprunner import HttpRunner

logger = logging.getLogger('HttpRunnerManager')


# Create your views here.


def login(request):
    """
    登录
    :param request:
    :return:
    """
    if request.method == 'POST':
        username = request.POST.get('account')
        password = request.POST.get('password')

        if UserInfo.objects.filter(username__exact=username).filter(password__exact=password).count() == 1:
            logger.info('{username} 登录成功'.format(username=username))
            request.session["login_status"] = True
            request.session["now_account"] = username
            return HttpResponseRedirect('/api/index/')
        else:
            logger.info('{username} 登录失败, 请检查用户名或者密码'.format(username=username))
            request.session["login_status"] = False
            return render_to_response("login.html")
    elif request.method == 'GET':
        return render_to_response("login.html")


def register(request):
    """
    注册
    :param request:
    :return:
    """
    if request.is_ajax():
        user_info = json.loads(request.body.decode('utf-8'))
        msg = register_info_logic(**user_info)
        return HttpResponse(get_ajax_msg(msg, '恭喜您，账号已成功注册'))
    elif request.method == 'GET':
        return render_to_response("register.html")


def log_out(request):
    """
    注销登录
    :param request:
    :return:
    """
    if request.method == 'GET':
        logger.info('{username}退出'.format(username=request.session['now_account']))
        try:
            del request.session['now_account']
        except KeyError:
            logging.error('session invalid')
        return HttpResponseRedirect("/api/login/")


def index(request):
    """
    首页
    :param request:
    :return:
    """
    if request.session.get('login_status'):
        project_length = ProjectInfo.objects.count()
        module_length = ModuleInfo.objects.count()
        test_length = TestCaseInfo.objects.filter(type__exact=1).count()
        config_length = TestCaseInfo.objects.filter(type__exact=2).count()
        manage_info = {
            'project_length': project_length,
            'module_length': module_length,
            'test_length': test_length,
            'config_length': config_length,
            'account': request.session["now_account"]
        }
        return render_to_response('index.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def add_project(request):
    """
    新增项目
    :param request:
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                project_info = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logger.error('项目信息解析异常: {project_info}'.format(project_info=project_info))
                return HttpResponse('项目信息新增异常')
            msg = project_info_logic(**project_info)
            return HttpResponse(get_ajax_msg(msg, '/api/project_list/1/'))

        elif request.method == 'GET':
            manage_info = {
                'account': acount
            }
            return render_to_response('add_project.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def add_module(request):
    """
    新增模块
    :param request:
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                module_info = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logger.error('模块信息解析异常：{module_info}'.format(module_info=module_info))
            msg = module_info_logic(**module_info)
            return HttpResponse(get_ajax_msg(msg, '/api/module_list/1/'))
        elif request.method == 'GET':
            manage_info = {
                'account': acount,
                'data': ProjectInfo.objects.all().values('project_name')
            }
            return render_to_response('add_module.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def add_case(request):
    """
    新增用例
    :param request:
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                testcase_info = json.loads(request.body.decode('utf-8'))
                print(testcase_info)
            except ValueError:
                logger.error('用例信息解析异常：{testcase_info}'.format(testcase_info=testcase_info))
                return '用例信息解析异常'
            msg = case_info_logic(**testcase_info)
            return HttpResponse(get_ajax_msg(msg, '/api/test_list/1/'))
        elif request.method == 'GET':
            manage_info = {
                'account': acount,
                'project': ProjectInfo.objects.all().values('project_name').order_by('-create_time'),
            }
            return render_to_response('add_case.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def add_config(request):
    """
    新增配置
    :param request:
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                testconfig_info = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logger.error('配置信息解析失败：{testconfig_info}'.format(testconfig_info=testconfig_info))
                return '配置信息解析异常'
            msg = config_info_logic(**testconfig_info)
            return HttpResponse(get_ajax_msg(msg, '/api/config_list/1/'))
        elif request.method == 'GET':
            manage_info = {
                'account': acount,
                'project': ProjectInfo.objects.all().values('project_name').order_by('-create_time')
            }
            return render_to_response('add_config.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def run_test(request):
    """
    运行用例
    :param request:
    :return:
    """
    if request.session.get('login_status'):
        kwargs = {
            "failfast": False,
        }
        runner = HttpRunner(**kwargs)
        if request.is_ajax():
            try:
                kwargs = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.error('待运行用例信息解析异常：{kwargs}'.format(kwargs=kwargs))
                return HttpResponse('信息解析异常，请重试')
            id = kwargs.pop('id')
            base_url = kwargs.pop('env_name')
            type = kwargs.pop('type')
            config = kwargs.pop('config')
            testcases_dict = run_by_module(id, base_url, config) if type == 'module' \
                else run_by_project(id, base_url, config)
            report_name = kwargs.get('report_name', None)
            if not testcases_dict:
                return HttpResponse('没有用例哦')
            main_hrun.delay(testcases_dict, report_name)
            return HttpResponse('用例执行中，请稍后查看报告即可,默认时间戳命名报告')
        else:
            id = request.POST.get('id')
            base_url = request.POST.get('env_name')
            config = request.POST.get('config')
            type = request.POST.get('type', None)
            if type:
                testcases_dict = run_by_module(id, base_url, config) if type == 'module' \
                    else run_by_project(id, base_url, config)
            else:
                testcases_dict = run_by_single(id, base_url, config)
            if testcases_dict:
                runner.run(testcases_dict)
                return render_to_response('report_template.html', runner.summary)
            else:
                return HttpResponseRedirect('/api/index/')
    else:
        return HttpResponseRedirect("/api/login/")


def run_batch_test(request):
    """
    批量运行用例
    :param request:
    :return:
    """
    if request.session.get('login_status'):
        kwargs = {
            "failfast": False,
        }
        runner = HttpRunner(**kwargs)
        if request.is_ajax():
            try:
                kwargs = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.error('待运行用例信息解析异常：{kwargs}'.format(kwargs=kwargs))
                return HttpResponse('信息解析异常，请重试')
            test_list = kwargs.pop('id')
            base_url = kwargs.pop('env_name')
            type = kwargs.pop('type')
            config = kwargs.pop('config')
            report_name = kwargs.get('report_name', None)
            testcases_dict = run_by_batch(test_list, base_url, config, type=type)
            if not testcases_dict:
                return HttpResponse('没有用例哦')
            main_hrun.delay(testcases_dict, report_name)
            return HttpResponse('用例执行中，请稍后查看报告即可,默认时间戳命名报告')
        else:
            type = request.POST.get('type', None)
            base_url = request.POST.get('env_name')
            config = request.POST.get('config')
            test_list = request.body.decode('utf-8').split('&')
            if type:
                testcases_lists = run_by_batch(test_list, base_url, config, type=type, mode=True)
            else:
                testcases_lists = run_by_batch(test_list, base_url, config)
            if testcases_lists:
                runner.run(testcases_lists)
                return render_to_response('report_template.html', runner.summary)
            else:  # 没有用例默认重定向到首页
                return HttpResponseRedirect('/api/index/')
    else:
        return HttpResponseRedirect("/api/login/")


def project_list(request, id):
    """
    项目列表
    :param request:
    :param id: str or int：当前页
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                project_info = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.debug('项目信息解析异常：{project_info}'.format(project_info=project_info))
                return HttpResponse('项目信息解析异常')
            if 'mode' in project_info.keys():
                msg = del_project_data(project_info.pop('id'))
            else:
                msg = project_info_logic(type=False, **project_info)
            return HttpResponse(get_ajax_msg(msg, 'ok'))
        else:
            filter_query = set_filter_session(request)
            pro_list = get_pager_info(
                ProjectInfo, filter_query, '/api/project_list/', id)
            manage_info = {
                'account': acount,
                'project': pro_list[1],
                'page_list': pro_list[0],
                'info': filter_query,
                'sum': pro_list[2],
                'env': EnvInfo.objects.all().order_by('-create_time')
            }
            return render_to_response('project_list.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def module_list(request, id):
    """
    模块列表
    :param request:
    :param id: str or int：当前页
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                module_info = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.error('模块信息解析异常：{module_info}'.format(module_info=module_info))
                return HttpResponse('模块信息解析异常')
            if 'mode' in module_info.keys():  # del module
                msg = del_module_data(module_info.pop('id'))
            else:
                msg = module_info_logic(type=False, **module_info)
            return HttpResponse(get_ajax_msg(msg, 'ok'))
        else:
            filter_query = set_filter_session(request)
            module_list = get_pager_info(
                ModuleInfo, filter_query, '/api/module_list/', id)
            manage_info = {
                'account': acount,
                'module': module_list[1],
                'page_list': module_list[0],
                'info': filter_query,
                'sum': module_list[2],
                'env': EnvInfo.objects.all().order_by('-create_time')
            }
            return render_to_response('module_list.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def test_list(request, id):
    """
    用例列表
    :param request:
    :param id: str or int：当前页
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                test_info = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.error('用例信息解析异常：{test_info}'.format(test_info=test_info))
                return HttpResponse('用例信息解析异常')
            if test_info.get('mode') == 'del':
                msg = del_test_data(test_info.pop('id'))
            elif test_info.get('mode') == 'copy':
                msg = copy_test_data(test_info.get('data').pop('index'), test_info.get('data').pop('name'))
            return HttpResponse(get_ajax_msg(msg, 'ok'))

        else:
            filter_query = set_filter_session(request)
            test_list = get_pager_info(
                TestCaseInfo, filter_query, '/api/test_list/', id)
            manage_info = {
                'account': acount,
                'test': test_list[1],
                'page_list': test_list[0],
                'info': filter_query,
                'env': EnvInfo.objects.all().order_by('-create_time')
            }
            return render_to_response('test_list.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def config_list(request, id):
    """
    配置列表
    :param request:
    :param id: str or int：当前页
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                test_info = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.error('配置信息解析异常：{test_info}'.format(test_info=test_info))
                return HttpResponse('配置信息解析异常')
            if test_info.get('mode') == 'del':
                msg = del_test_data(test_info.pop('id'))
            elif test_info.get('mode') == 'copy':
                msg = copy_test_data(test_info.get('data').pop('index'), test_info.get('data').pop('name'))
            return HttpResponse(get_ajax_msg(msg, 'ok'))
        else:
            filter_query = set_filter_session(request)
            test_list = get_pager_info(
                TestCaseInfo, filter_query, '/api/config_list/', id)
            manage_info = {
                'account': acount,
                'test': test_list[1],
                'page_list': test_list[0],
                'info': filter_query
            }
            return render_to_response('config_list.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def edit_case(request, id=None):
    """
    编辑用例
    :param request:
    :param id:
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                testcase_lists = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logger.error('用例信息解析异常：{testcase_lists}'.format(testcase_lists=testcase_lists))
                return HttpResponse('用例信息解析异常')
            msg = case_info_logic(type=False, **testcase_lists)
            return HttpResponse(get_ajax_msg(msg, '/api/test_list/1/'))

        test_info = TestCaseInfo.objects.get_case_by_id(id)
        request = eval(test_info[0].request)
        manage_info = {
            'account': acount,
            'info': test_info[0],
            'request': request['test'],
            'project': ProjectInfo.objects.all().values('project_name').order_by('-create_time')
        }
        return render_to_response('edit_case.html', manage_info)

    else:
        return HttpResponseRedirect("/api/login/")


def edit_config(request, id=None):
    """
    编辑配置
    :param request:
    :param id:
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                testconfig_lists = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logger.error('配置更新处理之前数据：{testconfig_lists}'.format(testconfig_lists=testconfig_lists))
            msg = config_info_logic(type=False, **testconfig_lists)
            return HttpResponse(get_ajax_msg(msg, '/api/config_list/1/'))

        config_info = TestCaseInfo.objects.get_case_by_id(id)
        request = eval(config_info[0].request)
        manage_info = {
            'account': acount,
            'info': config_info[0],
            'request': request['config'],
            'project': ProjectInfo.objects.all().values(
                'project_name').order_by('-create_time')
        }
        return render_to_response('edit_config.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def env_set(request):
    """
    环境设置
    :param request:
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                env_lists = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.error('环境信息解析异常：{env_lists}'.format(env_lists=env_lists))
                return HttpResponse('环境信息查询异常，请重试')
            msg = env_data_logic(**env_lists)
            return HttpResponse(get_ajax_msg(msg, 'ok'))

        elif request.method == 'GET':
            return render_to_response('env_list.html', {'account': acount})

    else:
        return HttpResponseRedirect("/api/login/")


def env_list(request, id):
    """
    环境列表
    :param request:
    :param id: str or int：当前页
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.method == 'GET':
            env_lists = get_pager_info(
                EnvInfo, None, '/api/env_list/', id)
            manage_info = {
                'account': acount,
                'env': env_lists[1],
                'page_list': env_lists[0],
            }
            return render_to_response('env_list.html', manage_info)
    else:
        return HttpResponseRedirect('/api/login/')


def report_list(request, id):
    """
    报告列表
    :param request:
    :param id: str or int：当前页
    :return:
    """
    if request.session.get('login_status'):
        if request.is_ajax():
            try:
                report_info = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.error('报告信息解析异常：{report_info}'.format(report_info=report_info))
                return HttpResponse('报告信息解析异常')
            if report_info.get('mode') == 'del':
                msg = del_report_data(report_info.pop('id'))
            return HttpResponse(get_ajax_msg(msg, 'ok'))
        else:
            filter_query = set_filter_session(request)
            report_list = get_pager_info(
                TestReports, filter_query, '/api/report_list/', id)
            manage_info = {
                'account': request.session["now_account"],
                'report': report_list[1],
                'page_list': report_list[0],
                'info': filter_query
            }
            return render_to_response('report_list.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def view_report(request, id):
    """
    查看报告
    :param request:
    :param id: str or int：报告名称索引
    :return:
    """
    if request.session.get('login_status'):
        reports = eval(TestReports.objects.get(id=id).reports)
        reports.get('time')['start_at'] = TestReports.objects.get(id=id).start_at
        return render_to_response('report_template.html', reports)
    else:
        return HttpResponseRedirect("/api/login/")


def periodictask(request, id):
    """
    定时任务列表
    :param request:
    :param id: str or int：当前页
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                kwargs = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.error('定时任务信息解析异常: {kwargs}'.format(kwargs=kwargs))
                return HttpResponse('定时任务信息解析异常，请重试')
            mode = kwargs.pop('mode')
            id = kwargs.pop('id')
            msg = delete_task(id) if mode == 'del' else change_task_status(id, mode)
            return HttpResponse(get_ajax_msg(msg, 'ok'))
        else:
            filter_query = set_filter_session(request)
            task_list = get_pager_info(
                PeriodicTask, filter_query, '/api/periodictask/', id)
            manage_info = {
                'account': acount,
                'task': task_list[1],
                'page_list': task_list[0],
                'info': filter_query
            }
        return render_to_response('periodictask_list.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


def load_config(request):
    """
    接收ajax请求，返回指定项目下的配置
    :param request:
    :return:
    """
    if request.session.get('login_status'):
        if request.is_ajax():
            try:
                kwargs = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.error('指定项目信息解析异常: {kwargs}'.format(kwargs=kwargs))
                return '配置信息加载异常'
            msg = load_configs()
            return HttpResponse(msg)


def add_task(request):
    """
    添加任务
    :param request:
    :return:
    """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                kwargs = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logging.error('定时任务信息解析异常: {kwargs}'.format(kwargs=kwargs))
                return HttpResponse('定时任务信息解析异常，请重试')
            msg = task_logic(**kwargs)
            return HttpResponse(get_ajax_msg(msg, '/api/periodictask/1/'))
        elif request.method == 'GET':
            info = {
                'account': acount,
                'env': EnvInfo.objects.all().order_by('-create_time'),
                'project': ProjectInfo.objects.all().order_by('-create_time')
            }
            return render_to_response('add_task.html', info)
    else:
        return HttpResponseRedirect("/api/login/")


def test_login(request):
    if request.POST.get('username') == 'lcc' and request.POST.get('password') == 'lcc':
        return JsonResponse({'code': 'success', 'status': True})


def test_deposit(request):
    if request.POST.get('code') == 'success' and request.POST.get('money') == '1':
        return JsonResponse({'code': 'error', 'status': False})


def test_index(request, id):
    return JsonResponse({'code': 'error', 'status': False})


def upload_file(request):
    import os
    if request.method == 'GET':
        return HttpResponse('上传失败，请使用POST方法上传文件')
    elif request.method == 'POST':
        # 用于获取前端批量上传上来的文件，Django默认只能接收一个文件，使用getlist接收多个文件
        try:
            project_name = request.POST.get('project')
            module_name = request.POST.get('module')
        except Exception as e:
            respon = json.dumps({"status": e})
            return HttpResponse(respon)
        obj = request.FILES.getlist('upload')
        pro_path = sys.path[0]
        upload_path = pro_path+'/upload/'
        import shutil
        # 清空upload下所有文件
        shutil.rmtree(upload_path)
        # 重建upload文件夹
        os.mkdir(upload_path)
        # 上传文件个数
        fileNum = len(obj)
        if fileNum > 1:
            print('批量上传开启')
            file_list = []
            for index,filename in enumerate(obj):
                temp_save = upload_path + filename.name
                file_list.append(temp_save)
                if '\\' in temp_save:
                    temp_save = temp_save.replace('\\\\', '\\')
                # 上传文件落地至upload文件夹
                try:

                    f = open(temp_save, 'wb')
                    for line in obj[index].chunks():
                        f.write(line)
                    f.close()
                except Exception as e:
                    respon = json.dumps({"status": e})
                    return HttpResponse(respon)
        elif fileNum == 1:
            print("单文件上传开启")
            print(obj[0])
            temp_save = upload_path + obj[0].name
            # windows 和linux兼容处理
            if '\\' in temp_save:
                temp_save = temp_save.replace('\\\\', '\\')
            # 上传文件落地至upload文件夹
            try:
                f = open(temp_save, 'wb')
                for line in obj[0].chunks():
                    f.write(line)
                f.close()
            except Exception as e:
                print(e)
                respon = json.dumps({"status": e})
                return HttpResponse(respon)
        else:
            respon = json.dumps({"status": u'文件上传失败，请重试'})
            return HttpResponse(respon)
        # 数据入库主逻辑
        if fileNum == 1:
            try:
                upload_file_logic(temp_save, project_name, module_name),
                respon = json.dumps({"status": "上传成功"})
                return HttpResponse(respon)
            except Exception as e:
                respon = json.dumps({"status": e})
                return HttpResponse(respon)
        elif fileNum > 1:
            for file in file_list:
                print(file)
                try:
                    upload_file_logic(file)
                    respon = json.dumps({"status": "上传成功"})
                except Exception as e:
                    respon = json.dumps({"status": e})
            return HttpResponse(respon)


def get_project_info(request):
    """
     获取项目相关信息
     :param request:
     :return:
     """
    if request.session.get('login_status'):
        acount = request.session["now_account"]
        if request.is_ajax():
            try:
                project_info = json.loads(request.body.decode('utf-8'))
            except ValueError:
                logger.error('用例信息解析异常：{testcase_info}'.format(testcase_info=project_info))
                return '用例信息解析异常'
            msg = load_modules(**project_info)
            return HttpResponse(get_ajax_msg(msg, '/api/test_list/1/'))
        elif request.method == 'GET':
            manage_info = {
                'account': acount,
                'project': ProjectInfo.objects.all().values('project_name').order_by('-create_time'),
            }
            return render_to_response('add_case.html', manage_info)
    else:
        return HttpResponseRedirect("/api/login/")


